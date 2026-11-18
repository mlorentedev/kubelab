package forge_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The writer contract mirrors the reader's (contract_test.go): one runner holds both
// adapters to the same behaviour, and everything that differs between forges is a row.
//
// The answers below are NOT recorded from a live forge: a write cannot be replayed against
// production, and staging has no forge writer (ADR-066 W7). They are built from the forges'
// own definitions, which each case cites: GitHub's REST description (api.github.com 2022-11-28,
// rest-api-description 1.1.4) and Gitea v1.27.3, the version prod runs (routers/api/v1/api.go,
// routers/api/v1/repo/issue.go, issue_label.go, issue_assignee.go). The first live write is
// the prod smoke test on personal/sandbox, which is what measures them.

// exchange is one request the adapter must make and the answer the fake forge gives.
type exchange struct {
	Method string
	// Path is the ESCAPED path, so a label with a space or a slash is pinned as it goes on the wire.
	Path string
	// Query, when set, is the raw query string the request must carry.
	Query string
	// Body is the request body decoded from JSON; nil means the request has no body.
	Body   any
	Status int
	Answer string
}

// wantResult is the part of a Result a contract row pins.
type wantResult struct {
	Outcome forge.Outcome
	Status  int
	Number  int
	URL     string
}

type writeCase struct {
	Name  string
	Write forge.Write
	Calls []exchange
	Want  wantResult
}

// writerContract is what differs between forges: how a request is authenticated and how to
// build the adapter around a fake server.
type writerContract struct {
	Forge   string
	Auth    string
	Headers map[string]string
	New     func(baseURL string) forge.Writer
	Cases   []writeCase
}

// fakeForge serves the expected exchanges in order and fails the test on any request it did
// not expect, so an adapter that makes an extra or a missing call is red, not green.
type fakeForge struct {
	t     *testing.T
	c     writerContract
	calls []exchange
	mu    sync.Mutex
	next  int
}

func (f *fakeForge) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.next >= len(f.calls) {
		f.t.Errorf("unexpected extra request %s %s", r.Method, r.URL.RequestURI())
		http.Error(w, "unexpected", http.StatusTeapot)
		return
	}
	want := f.calls[f.next]
	f.next++
	if r.Method != want.Method || r.URL.EscapedPath() != want.Path {
		f.t.Errorf("request %d: %s %s, want %s %s", f.next, r.Method, r.URL.EscapedPath(), want.Method, want.Path)
	}
	if want.Query != "" && r.URL.RawQuery != want.Query {
		f.t.Errorf("request %d: query %q, want %q", f.next, r.URL.RawQuery, want.Query)
	}
	if got := r.Header.Get("Authorization"); got != f.c.Auth {
		f.t.Errorf("request %d: Authorization %q, want %q", f.next, got, f.c.Auth)
	}
	for k, v := range f.c.Headers {
		if got := r.Header.Get(k); got != v {
			f.t.Errorf("request %d: header %s=%q, want %q", f.next, k, got, v)
		}
	}
	raw, _ := io.ReadAll(r.Body)
	if want.Body == nil {
		if len(raw) != 0 {
			f.t.Errorf("request %d: unexpected body %s", f.next, raw)
		}
	} else {
		var got any
		if err := json.Unmarshal(raw, &got); err != nil {
			f.t.Errorf("request %d: body is not JSON: %q", f.next, raw)
		} else if !reflect.DeepEqual(got, want.Body) {
			f.t.Errorf("request %d: body %s, want %v", f.next, raw, want.Body)
		}
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			f.t.Errorf("request %d: Content-Type %q", f.next, ct)
		}
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(want.Status)
	_, _ = w.Write([]byte(want.Answer))
}

func runWriterContract(t *testing.T, c writerContract) {
	t.Helper()
	for _, tc := range c.Cases {
		t.Run(tc.Name, func(t *testing.T) {
			f := &fakeForge{t: t, c: c, calls: tc.Calls}
			srv := httptest.NewServer(f)
			defer srv.Close()

			got := c.New(srv.URL).Write(context.Background(), tc.Write)
			if f.next != len(tc.Calls) {
				t.Errorf("made %d call(s), want %d", f.next, len(tc.Calls))
			}
			have := wantResult{Outcome: got.Outcome, Status: got.Status, Number: got.Number, URL: got.URL}
			if have != tc.Want {
				t.Fatalf("result %+v (err=%v), want %+v", have, got.Err, tc.Want)
			}
			if got.Outcome != forge.OutcomeApplied && got.Err == nil {
				t.Errorf("a %s result must carry its cause", got.Outcome)
			}
			if got.Outcome == forge.OutcomeApplied && got.Err != nil {
				t.Errorf("an applied result carries an error: %v", got.Err)
			}
		})
	}
}

// statusRow is the class a status falls in, for a create and for every other action.
type statusRow struct {
	Name       string
	Status     int
	Header     map[string]string
	Body       string
	Create     forge.Outcome
	Other      forge.Outcome
	RetryAfter time.Duration
}

// The failure classes of ADR-066 W3 and W8. A create never reads a non-2xx that may have been
// processed as "retry": it is UNKNOWN until the marker is searched. A definite refusal (a 4xx
// other than 429, and a redirect, which the forge answers before it acts) is terminal.
func statusRows() []statusRow {
	f, r, u := forge.OutcomeFailed, forge.OutcomeRetry, forge.OutcomeUnknown
	return []statusRow{
		{Name: "400", Status: 400, Create: f, Other: f},
		{Name: "401", Status: 401, Create: f, Other: f},
		{Name: "403", Status: 403, Create: f, Other: f},
		{Name: "404", Status: 404, Create: f, Other: f},
		{Name: "409", Status: 409, Create: f, Other: f},
		{Name: "410", Status: 410, Create: f, Other: f},
		{Name: "422", Status: 422, Create: f, Other: f},
		{Name: "301 is refused, not followed", Status: 301, Create: f, Other: f},
		{Name: "307 is refused, not followed", Status: 307, Create: f, Other: f},
		{Name: "429", Status: 429, Create: u, Other: r},
		{Name: "429 with Retry-After", Status: 429, Header: map[string]string{"Retry-After": "30"}, Create: u, Other: r, RetryAfter: 30 * time.Second},
		// A negative or unreadable wait is no wait: the worker's backoff decides.
		{Name: "429 with a negative Retry-After", Status: 429, Header: map[string]string{"Retry-After": "-5"}, Create: u, Other: r},
		{Name: "429 with an unreadable Retry-After", Status: 429, Header: map[string]string{"Retry-After": "Wed, 18 Nov 2026 00:00:00 GMT"}, Create: u, Other: r},
		{Name: "500", Status: 500, Create: u, Other: r},
		{Name: "502", Status: 502, Create: u, Other: r},
		{Name: "503", Status: 503, Create: u, Other: r},
		{Name: "504", Status: 504, Create: u, Other: r},
		// GitHub signals its rate limits as a 403 too (primary: X-RateLimit-Remaining 0;
		// secondary: Retry-After). Terminal would drop an operator's write for a limit that lifts.
		{Name: "403 secondary rate limit", Status: 403, Header: map[string]string{"Retry-After": "60"}, Create: u, Other: r, RetryAfter: time.Minute},
		// GitHub's documented secondary-limit answer can carry neither header: only its message says so.
		// A permission refusal is a 403 too, and stays terminal.
		{Name: "403 secondary rate limit named only in the message", Status: 403, Body: `{"message":"You have exceeded a secondary rate limit. Please wait a few minutes before you try again."}`, Create: u, Other: r},
		{Name: "403 permission refusal with a message", Status: 403, Body: `{"message":"Resource not accessible by integration"}`, Create: f, Other: f},
		{Name: "403 primary rate limit", Status: 403, Header: map[string]string{"X-RateLimit-Remaining": "0"}, Create: u, Other: r},
	}
}

func runStatusClasses(t *testing.T, newWriter func(baseURL string) forge.Writer) {
	t.Helper()
	src := forge.Source{Owner: "o", Repo: "r"}
	create := forge.Write{Action: forge.ActionCreate, Source: src, OutboxID: 1, Title: "t"}
	label := forge.Write{Action: forge.ActionAddLabel, Source: src, Number: 5, Label: "x"}
	for _, row := range statusRows() {
		t.Run(row.Name, func(t *testing.T) {
			var elsewhere int
			other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { elsewhere++ }))
			defer other.Close()
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				for k, v := range row.Header {
					w.Header().Set(k, v)
				}
				if row.Status/100 == 3 {
					w.Header().Set("Location", other.URL+"/moved")
				}
				w.WriteHeader(row.Status)
				_, _ = w.Write([]byte(row.Body))
			}))
			defer srv.Close()

			w := newWriter(srv.URL)
			for _, c := range []struct {
				name string
				w    forge.Write
				want forge.Outcome
			}{{"create", create, row.Create}, {"add_label", label, row.Other}} {
				got := w.Write(context.Background(), c.w)
				if got.Outcome != c.want || got.Status != row.Status {
					t.Errorf("%s: %s with status %d, want %s with %d (err=%v)", c.name, got.Outcome, got.Status, c.want, row.Status, got.Err)
				}
				if got.Err == nil {
					t.Errorf("%s: no cause carried", c.name)
				}
				if got.RetryAfter != row.RetryAfter {
					t.Errorf("%s: RetryAfter %v, want %v", c.name, got.RetryAfter, row.RetryAfter)
				}
			}
			if elsewhere != 0 {
				t.Errorf("a write followed a redirect to another host %d time(s)", elsewhere)
			}
		})
	}
}

// What the adapter does when the forge says nothing. A create that may have been sent is
// UNKNOWN (W8); one that provably was not (the call ceiling, a token that did not mint) is
// retryable, since nothing reached the forge; every other action is retryable either way.
func runNoAnswer(t *testing.T, newWriter func(baseURL string) forge.Writer, withHTTP func(forge.Writer, *http.Client)) {
	t.Helper()
	src := forge.Source{Owner: "o", Repo: "r"}
	create := forge.Write{Action: forge.ActionCreate, Source: src, OutboxID: 1, Title: "t"}
	label := forge.Write{Action: forge.ActionAddLabel, Source: src, Number: 5, Label: "x"}

	t.Run("a refused connection is unknown for a create and retryable for the rest", func(t *testing.T) {
		srv := httptest.NewServer(http.NotFoundHandler())
		url := srv.URL
		srv.Close()
		w := newWriter(url)
		if got := w.Write(context.Background(), create); got.Outcome != forge.OutcomeUnknown || got.Status != 0 || got.Err == nil {
			t.Errorf("create: %+v", got)
		}
		if got := w.Write(context.Background(), label); got.Outcome != forge.OutcomeRetry || got.Status != 0 || got.Err == nil {
			t.Errorf("add_label: %+v", got)
		}
	})

	t.Run("a timeout is unknown for a create, and the forge may still finish it", func(t *testing.T) {
		release := make(chan struct{})
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-release }))
		defer srv.Close()
		defer close(release)
		w := newWriter(srv.URL)
		withHTTP(w, &http.Client{Timeout: 50 * time.Millisecond})
		if got := w.Write(context.Background(), create); got.Outcome != forge.OutcomeUnknown {
			t.Errorf("create: %+v", got)
		}
		if got := w.Write(context.Background(), label); got.Outcome != forge.OutcomeRetry {
			t.Errorf("add_label: %+v", got)
		}
	})

	t.Run("a spent call ceiling sent nothing, so even a create is retryable", func(t *testing.T) {
		var hits int
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
		defer srv.Close()
		w := newWriter(srv.URL)
		withHTTP(w, &http.Client{Transport: &forge.Ceiling{Limit: 0}})
		got := w.Write(context.Background(), create)
		if got.Outcome != forge.OutcomeRetry || !errors.Is(got.Err, forge.ErrCeiling) {
			t.Errorf("create: %+v", got)
		}
		if hits != 0 {
			t.Errorf("the forge was called %d time(s) past the ceiling", hits)
		}
	})
}

// A write the adapter cannot make well-formed is refused before any call: the forge is never
// asked, and the cause names what is missing.
func runInvalidWrites(t *testing.T, newWriter func(baseURL string) forge.Writer) {
	t.Helper()
	src := forge.Source{Owner: "o", Repo: "r"}
	for _, tc := range []struct {
		name string
		w    forge.Write
	}{
		{"unknown action", forge.Write{Action: "merge", Source: src, Number: 1}},
		{"empty action", forge.Write{Source: src, Number: 1}},
		{"create without a title", forge.Write{Action: forge.ActionCreate, Source: src, OutboxID: 1}},
		{"create without an outbox id", forge.Write{Action: forge.ActionCreate, Source: src, Title: "t"}},
		{"close without a number", forge.Write{Action: forge.ActionClose, Source: src}},
		{"add_label without a label", forge.Write{Action: forge.ActionAddLabel, Source: src, Number: 1}},
		{"remove_label without a label", forge.Write{Action: forge.ActionRemoveLabel, Source: src, Number: 1}},
		{"add_assignee without a login", forge.Write{Action: forge.ActionAddAssignee, Source: src, Number: 1}},
		{"remove_assignee without a login", forge.Write{Action: forge.ActionRemoveAssignee, Source: src, Number: 1}},
		{"a wildcard repository", forge.Write{Action: forge.ActionClose, Source: forge.Source{Owner: "o", Repo: forge.EveryRepo}, Number: 1}},
		{"no repository", forge.Write{Action: forge.ActionClose, Source: forge.Source{Owner: "o"}, Number: 1}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var hits int
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
			defer srv.Close()
			got := newWriter(srv.URL).Write(context.Background(), tc.w)
			if got.Outcome != forge.OutcomeFailed || got.Err == nil || got.Status != 0 {
				t.Errorf("got %+v, want a terminal failure with no status", got)
			}
			if hits != 0 {
				t.Errorf("the forge was called %d time(s) for a write that cannot be made", hits)
			}
		})
	}
}

// A body that cannot be read changes nothing about a status that arrived: a refusal is still a
// refusal, and a 2xx whose body is lost is not trusted (a create is UNKNOWN, the issue may exist).
func runTruncatedAnswers(t *testing.T, newWriter func(baseURL string) forge.Writer) {
	t.Helper()
	src := forge.Source{Owner: "o", Repo: "r"}
	truncated := func(status string) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			conn, buf, err := w.(http.Hijacker).Hijack()
			if err != nil {
				return
			}
			defer conn.Close()
			_, _ = buf.WriteString("HTTP/1.1 " + status + "\r\nContent-Length: 100\r\nContent-Type: application/json\r\n\r\n{\"mess")
			_ = buf.Flush()
		}))
	}
	t.Run("a 4xx whose body is cut short is still terminal", func(t *testing.T) {
		srv := truncated("400 Bad Request")
		defer srv.Close()
		got := newWriter(srv.URL).Write(context.Background(), forge.Write{Action: forge.ActionAddLabel, Source: src, Number: 5, Label: "x"})
		if got.Outcome != forge.OutcomeFailed || got.Status != 400 {
			t.Errorf("got %+v", got)
		}
	})
	t.Run("a 2xx create whose body is cut short is unknown", func(t *testing.T) {
		srv := truncated("201 Created")
		defer srv.Close()
		got := newWriter(srv.URL).Write(context.Background(), forge.Write{Action: forge.ActionCreate, Source: src, OutboxID: 1, Title: "t"})
		if got.Outcome != forge.OutcomeUnknown || got.Status != 201 || got.Err == nil {
			t.Errorf("got %+v", got)
		}
	})
}
