package console

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

type fakeQueue struct {
	states []forge.SourceState
	items  []forge.Item
	total  int
	err    error
	asked  []forge.Source
	after  *forge.QueueKey
	limit  int
}

func (f *fakeQueue) Queue(_ context.Context, sources []forge.Source, after *forge.QueueKey, limit int) (forge.QueuePage, error) {
	f.asked, f.after, f.limit = sources, after, limit
	items := f.items
	if len(items) > limit {
		items = items[:limit]
	}
	return forge.QueuePage{States: f.states, Items: items, Total: f.total}, f.err
}

const consoleHost = "console.kubelab.live"

func serveHost(t *testing.T, q QueueReader, sources, domain, host, path string) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	declared, err := forge.ParseSources(sources)
	if err != nil {
		t.Fatal(err)
	}
	Register(r, func() (QueueReader, []forge.Source, error) { return q, declared, nil }, func() string { return domain }, nil)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Host = host
	r.ServeHTTP(w, req)
	return w
}

func serve(t *testing.T, q QueueReader, sources string, path string) *httptest.ResponseRecorder {
	return serveHost(t, q, sources, consoleHost, consoleHost, path)
}

// The API binary also answers its public host, which has no session in front.
func TestConsoleIsServedOnlyOnItsOwnHost(t *testing.T) {
	cases := []struct{ name, domain, host string }{
		{"public api host", consoleHost, "api.kubelab.live"},
		{"no console host declared", "", consoleHost},
		{"no host at all", consoleHost, ""},
		{"neither declared nor named", "", ""},
	}
	for _, c := range cases {
		for _, path := range []string{"/console/", "/console/queue", "/console"} {
			if w := serveHost(t, &fakeQueue{}, "", c.domain, c.host, path); w.Code != http.StatusNotFound {
				t.Fatalf("%s %s: status = %d, want 404", c.name, path, w.Code)
			}
		}
	}
	if w := serveHost(t, &fakeQueue{}, "", consoleHost, "Console.Kubelab.Live:443", "/console/"); w.Code != http.StatusOK {
		t.Fatalf("console host with port and case: status = %d", w.Code)
	}
}

func TestQueueAnswersSourcesAndItems(t *testing.T) {
	read := time.Date(2026, 11, 3, 6, 49, 0, 0, time.UTC)
	src := forge.Source{Forge: "github", Owner: "mlorentedev", Repo: "kubelab"}
	never := forge.Source{Forge: "gitea", Owner: "personal", Repo: "resume"}
	q := &fakeQueue{
		states: []forge.SourceState{{Source: src, AsOf: &read, Reachable: true}, {Source: never}},
		items: []forge.Item{{Source: src, Number: 7, Kind: forge.KindPull, Title: "t", State: "open",
			Author: "a", URL: "https://github.com/mlorentedev/kubelab/pull/7", UpdatedAt: read}},
	}
	w := serve(t, q, "github:mlorentedev/kubelab,gitea:personal/resume", "/console/queue")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d", w.Code)
	}
	if len(q.asked) != 2 || q.asked[1] != never {
		t.Fatalf("queue asked for %v, want the declared sources", q.asked)
	}
	var body struct {
		Sources []struct {
			Source    string     `json:"source"`
			AsOf      *time.Time `json:"as_of"`
			Reachable bool       `json:"reachable"`
		} `json:"sources"`
		Items []struct {
			Source, Kind, Title, URL string
			Number                   int
		} `json:"items"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(body.Sources) != 2 || body.Sources[0].Source != "github:mlorentedev/kubelab" ||
		!body.Sources[0].Reachable || body.Sources[0].AsOf == nil {
		t.Fatalf("sources = %+v", body.Sources)
	}
	// A source never read is shown, unreachable and with no time, never dropped.
	if body.Sources[1].Reachable || body.Sources[1].AsOf != nil {
		t.Fatalf("never-read source = %+v", body.Sources[1])
	}
	if len(body.Items) != 1 || body.Items[0].Number != 7 || body.Items[0].Kind != "pull" ||
		body.Items[0].Source != "github:mlorentedev/kubelab" {
		t.Fatalf("items = %+v", body.Items)
	}
}

type pageBody struct {
	Items []struct{ Number int } `json:"items"`
	Total int                    `json:"total"`
	Next  *string                `json:"next"`
}

func decodePage(t *testing.T, w *httptest.ResponseRecorder) pageBody {
	t.Helper()
	var b pageBody
	if err := json.Unmarshal(w.Body.Bytes(), &b); err != nil {
		t.Fatalf("status %d body %s: %v", w.Code, w.Body.String(), err)
	}
	return b
}

// A page names the next one by the last item it holds, and the cursor comes back
// as that item's key; the last page names none.
func TestQueuePagesCarryANextCursor(t *testing.T) {
	src := forge.Source{Forge: "github", Owner: "mlorentedev", Repo: "kubelab"}
	at := time.Date(2026, 11, 5, 9, 0, 0, 123456000, time.UTC)
	var items []forge.Item
	for n := 5; n >= 1; n-- {
		items = append(items, forge.Item{Source: src, Number: n, Kind: forge.KindIssue, UpdatedAt: at})
	}
	q := &fakeQueue{items: items, total: 5}
	const decl = "github:mlorentedev/kubelab"

	first := decodePage(t, serve(t, q, decl, "/console/queue?limit=2"))
	if len(first.Items) != 2 || first.Total != 5 || first.Next == nil || q.after != nil || q.limit != 3 {
		t.Fatalf("first page = %+v, asked after %v limit %d", first, q.after, q.limit)
	}
	serve(t, q, decl, "/console/queue?limit=2&after="+*first.Next)
	if want := items[1].Key(); q.after == nil || *q.after != want {
		t.Fatalf("cursor came back as %+v, want %+v", q.after, want)
	}

	last := decodePage(t, serve(t, q, decl, "/console/queue"))
	if len(last.Items) != 5 || last.Next != nil {
		t.Fatalf("a page holding everything names a next one: %+v", last)
	}
}

// The cursor and the limit are client input.
func TestQueueRefusesABadPageRequest(t *testing.T) {
	// A wildcard names no one item, so a cursor carrying one is not a position.
	wildcard := encodeCursor(forge.QueueKey{UpdatedAt: time.Now(), Number: 1,
		Source: forge.Source{Forge: "github", Owner: "mlorentedev", Repo: forge.EveryRepo}})
	for _, query := range []string{"after=not-base64!", "after=e30", "after=" + encodeCursor(forge.QueueKey{}),
		"after=" + wildcard, "limit=0", "limit=501", "limit=ten"} {
		if w := serve(t, &fakeQueue{}, "github:mlorentedev/kubelab", "/console/queue?"+query); w.Code != http.StatusBadRequest {
			t.Fatalf("%s: status = %d, want 400", query, w.Code)
		}
	}
}

func TestQueueStoreDownIs503(t *testing.T) {
	w := serve(t, &fakeQueue{err: errors.New("down")}, "github:mlorentedev/kubelab", "/console/queue")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", w.Code)
	}
}

func TestQueueWithoutSourcesIsEmptyNotAnError(t *testing.T) {
	q := &fakeQueue{}
	w := serve(t, q, "", "/console/queue")
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"items":[]`) || q.asked != nil {
		t.Fatalf("status = %d body = %s asked = %v", w.Code, w.Body.String(), q.asked)
	}
}

func TestConsolePageIsServed(t *testing.T) {
	w := serve(t, &fakeQueue{}, "", "/console/")
	if w.Code != http.StatusOK || !strings.HasPrefix(w.Header().Get("Content-Type"), "text/html") ||
		!strings.Contains(w.Body.String(), "queue") {
		t.Fatalf("status = %d type = %q", w.Code, w.Header().Get("Content-Type"))
	}
}

// Every key the server can emit as `next` must be one it accepts back: an item whose
// update time is the zero time would otherwise leave "Load more" answering 400 forever.
func TestEveryEmittedCursorDecodes(t *testing.T) {
	src := forge.Source{Forge: "github", Owner: "mlorentedev", Repo: "kubelab"}
	for _, k := range []forge.QueueKey{
		{UpdatedAt: time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC), Source: src, Number: 3},
		{Source: src, Number: 3},
	} {
		got, err := decodeCursor(encodeCursor(k))
		if err != nil {
			t.Fatalf("cursor for %+v refused: %v", k, err)
		}
		if !got.UpdatedAt.Equal(k.UpdatedAt) || got.Source != k.Source || got.Number != k.Number {
			t.Fatalf("cursor for %+v decoded as %+v", k, *got)
		}
	}
}

// Until apps/console serves the host's root (ADR-074 D5), the bare host sends the
// operator to the page. The redirect is temporary on purpose: a browser caches a 301
// for good, and `/` will become the frontend's.
func TestConsoleHostRootRedirectsToThePage(t *testing.T) {
	w := serve(t, &fakeQueue{}, "", "/")
	if w.Code != http.StatusFound || w.Header().Get("Location") != "/console/" {
		t.Fatalf("console host /: status = %d, location = %q, want 302 to /console/", w.Code, w.Header().Get("Location"))
	}
	for _, c := range []struct{ name, domain, host string }{
		{"public api host", consoleHost, "api.kubelab.live"},
		{"no console host declared", "", consoleHost},
	} {
		if w := serveHost(t, &fakeQueue{}, "", c.domain, c.host, "/"); w.Code != http.StatusNotFound {
			t.Fatalf("%s /: status = %d, want 404", c.name, w.Code)
		}
	}
}

// A declaration that does not parse leaves no catalog; the queue says so with a
// 503 rather than an empty page that reads as "nothing open".
func TestQueueWithoutACatalogIs503(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	Register(r, Live(&fakeQueue{}, nil), func() string { return consoleHost }, nil)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/console/queue", nil)
	req.Host = consoleHost
	r.ServeHTTP(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", w.Code)
	}
}

// A wildcard the catalog has not listed yet is shown, so the page reports it
// unreachable rather than leaving that forge out without a word.
func TestQueueShowsAWildcardNotYetListed(t *testing.T) {
	sources, err := forge.ParseSources("github:o/*")
	if err != nil {
		t.Fatal(err)
	}
	q := &fakeQueue{}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	Register(r, Live(q, &forge.Catalog{Declared: sources}), func() string { return consoleHost }, nil)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/console/queue", nil)
	req.Host = consoleHost
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK || len(q.asked) != 1 || !q.asked[0].Wildcard() {
		t.Fatalf("status %d, asked %v", w.Code, q.asked)
	}
}
