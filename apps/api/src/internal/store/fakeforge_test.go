package store_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeForge is a Gitea over HTTP: the issue endpoints the writer calls, enough state to answer
// them, and the faults a real forge has. The writer under test is the real GiteaWriter, so what
// is held here is the loop (route to confirmed row), not the adapter's classification.
type fakeForge struct {
	t   *testing.T
	srv *httptest.Server

	mu     sync.Mutex
	issues map[int]*fakeIssue
	next   int
	// requests lists "METHOD path" of every request, in arrival order.
	requests []string

	// fail, when it returns a status, answers the request with it and does nothing else.
	fail func(method, path string) int
	// createDelay holds a create for this long BEFORE the forge makes the issue, and makes it
	// whether or not the client is still there: a client's timeout does not end the forge's work.
	createDelay time.Duration
	// onWrite runs, before the forge acts, for every request that is not a read.
	onWrite func()
	// dropCreate swallows a create: the connection ends with no answer and no issue is made.
	dropCreate bool
}

type fakeIssue struct {
	Number int
	Title  string
	Body   string
	State  string
	Labels []string
}

func newFakeForge(t *testing.T) *fakeForge {
	t.Helper()
	f := &fakeForge{t: t, issues: map[int]*fakeIssue{}, next: 1}
	f.srv = httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(f.srv.Close)
	return f
}

func (f *fakeForge) issueCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.issues)
}

func (f *fakeForge) set(change func(*fakeForge)) {
	f.mu.Lock()
	defer f.mu.Unlock()
	change(f)
}

func (f *fakeForge) issue(n int) *fakeIssue {
	f.mu.Lock()
	defer f.mu.Unlock()
	if i, ok := f.issues[n]; ok {
		c := *i
		return &c
	}
	return nil
}

func (f *fakeForge) sent() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.requests...)
}

func (f *fakeForge) count(prefix string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := 0
	for _, r := range f.requests {
		if strings.HasPrefix(r, prefix) {
			n++
		}
	}
	return n
}

// seed puts an issue in the forge, as if someone opened it there.
func (f *fakeForge) seed(title string, labels ...string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := f.next
	f.next++
	f.issues[n] = &fakeIssue{Number: n, Title: title, State: "open", Labels: labels}
	return n
}

func (f *fakeForge) body(i *fakeIssue) map[string]any {
	labels := []map[string]any{}
	for k, l := range i.Labels {
		labels = append(labels, map[string]any{"id": k + 1, "name": l})
	}
	return map[string]any{
		"number": i.Number, "html_url": fmt.Sprintf("%s/o/r/issues/%d", f.srv.URL, i.Number),
		"title": i.Title, "body": i.Body, "state": i.State, "labels": labels, "assignees": []any{},
	}
}

func (f *fakeForge) serve(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/v1/repos/o/r/issues")
	f.mu.Lock()
	f.requests = append(f.requests, r.Method+" "+r.URL.Path)
	fail, onWrite := f.fail, f.onWrite
	f.mu.Unlock()
	if onWrite != nil && r.Method != http.MethodGet {
		onWrite()
	}
	if fail != nil {
		if status := fail(r.Method, r.URL.Path); status != 0 {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"message":"injected"}`))
			return
		}
	}
	write := func(status int, v any) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(v)
	}
	switch {
	case path == "" && r.Method == http.MethodPost:
		f.create(w, r, write)
	case path == "" && r.Method == http.MethodGet:
		// The marker search: every issue, as a listing that does not page.
		f.mu.Lock()
		defer f.mu.Unlock()
		out := []map[string]any{}
		for n := 1; n < f.next; n++ {
			if i, ok := f.issues[n]; ok {
				out = append(out, f.body(i))
			}
		}
		write(http.StatusOK, out)
	default:
		f.issueRoute(w, r, path, write)
	}
}

func (f *fakeForge) create(w http.ResponseWriter, r *http.Request, write func(int, any)) {
	var in struct{ Title, Body string }
	_ = json.NewDecoder(r.Body).Decode(&in)
	f.mu.Lock()
	drop, delay := f.dropCreate, f.createDelay
	f.mu.Unlock()
	if drop {
		if hj, ok := w.(http.Hijacker); ok {
			conn, _, _ := hj.Hijack()
			_ = conn.Close()
		}
		return
	}
	if delay > 0 {
		time.Sleep(delay)
	}
	f.mu.Lock()
	n := f.next
	f.next++
	i := &fakeIssue{Number: n, Title: in.Title, Body: in.Body, State: "open"}
	f.issues[n] = i
	body := f.body(i)
	f.mu.Unlock()
	write(http.StatusCreated, body)
}

func (f *fakeForge) issueRoute(w http.ResponseWriter, r *http.Request, path string, write func(int, any)) {
	parts := strings.Split(strings.TrimPrefix(path, "/"), "/")
	number, err := strconv.Atoi(parts[0])
	f.mu.Lock()
	defer f.mu.Unlock()
	i, ok := f.issues[number]
	if err != nil || !ok {
		write(http.StatusNotFound, map[string]string{"message": "issue does not exist"})
		return
	}
	switch {
	case len(parts) == 1 && r.Method == http.MethodPatch:
		var in struct{ State string }
		_ = json.NewDecoder(r.Body).Decode(&in)
		if in.State != "" {
			i.State = in.State
		}
		write(http.StatusCreated, f.body(i))
	case len(parts) == 2 && parts[1] == "labels" && r.Method == http.MethodPost:
		var in struct{ Labels []string }
		_ = json.NewDecoder(r.Body).Decode(&in)
		for _, l := range in.Labels {
			if !hasString(i.Labels, l) {
				i.Labels = append(i.Labels, l)
			}
		}
		write(http.StatusOK, f.body(i)["labels"])
	default:
		write(http.StatusNotFound, map[string]string{"message": "not a route of the fake"})
	}
}

func hasString(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
