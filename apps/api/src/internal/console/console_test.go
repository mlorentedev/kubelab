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
	err    error
	asked  []forge.Source
}

func (f *fakeQueue) Queue(_ context.Context, sources []forge.Source) ([]forge.SourceState, []forge.Item, error) {
	f.asked = sources
	return f.states, f.items, f.err
}

const consoleHost = "console.kubelab.live"

func serveHost(t *testing.T, q QueueReader, sources, domain, host, path string) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	Register(r, func() (QueueReader, string, error) { return q, sources, nil }, func() string { return domain })
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
