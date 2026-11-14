package console

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

type usageCall struct {
	identity string
	at       time.Time
}

func serveUsage(t *testing.T, usage Usage, path string, header http.Header) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	Register(r, func() (QueueReader, []forge.Source, error) { return &fakeQueue{}, nil, nil }, func() string { return consoleHost }, usage)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Host = consoleHost
	for k, v := range header {
		req.Header[k] = v
	}
	r.ServeHTTP(w, req)
	return w
}

func recording(calls *[]usageCall, err error) Usage {
	return func(_ context.Context, identity string, at time.Time) (bool, error) {
		*calls = append(*calls, usageCall{identity, at})
		return true, err
	}
}

// A8 counts days the operator opened the page, read from the identity Authelia names.
func TestOpeningThePageCountsTheIdentityAutheliaNames(t *testing.T) {
	var calls []usageCall
	w := serveUsage(t, recording(&calls, nil), "/console/", http.Header{"Remote-User": {"operator"}})

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if len(calls) != 1 || calls[0].identity != "operator" || calls[0].at.IsZero() {
		t.Fatalf("calls = %+v, want one for operator", calls)
	}
}

// The host check can be met from inside the cluster; only Authelia sets Remote-User.
func TestARequestWithNoIdentityIsNotCounted(t *testing.T) {
	var calls []usageCall
	for _, h := range []http.Header{{}, {"Remote-User": {"  "}}} {
		if w := serveUsage(t, recording(&calls, nil), "/console/", h); w.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200", w.Code)
		}
	}
	if len(calls) != 0 {
		t.Fatalf("calls = %+v, want none", calls)
	}
}

// The frontend is a static page served by nginx: the queue is the one console route every load of
// it calls, so it is where an open is counted (#3450). Without this the A8 counter, which decides
// whether the console survives, would go silent the day the embedded page is deleted.
func TestTheQueueCountsTheIdentityAutheliaNames(t *testing.T) {
	var calls []usageCall
	w := serveUsage(t, recording(&calls, nil), "/console/queue", http.Header{"Remote-User": {"operator"}})
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if len(calls) != 1 || calls[0].identity != "operator" {
		t.Fatalf("calls = %+v, want one for operator", calls)
	}
}

// Fails if a console data route stops recording usage, or a new one is added that does not.
// Read from the engine's routes, not from a list here, so a route added later is held to it:
// every GET under /console other than the embedded page is data the frontend calls.
func TestEveryConsoleDataRouteCountsAnOpen(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	var calls []usageCall
	Register(r, func() (QueueReader, []forge.Source, error) { return &fakeQueue{}, nil, nil },
		func() string { return consoleHost }, recording(&calls, nil))

	seen := 0
	for _, ri := range r.Routes() {
		if ri.Method != http.MethodGet || !strings.HasPrefix(ri.Path, "/console") {
			continue
		}
		if ri.Path == "/console" || ri.Path == "/console/" {
			continue // the embedded page, deleted with its handler
		}
		seen++
		calls = nil
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, ri.Path, nil)
		req.Host = consoleHost
		req.Header.Set("Remote-User", "operator")
		r.ServeHTTP(w, req)
		if len(calls) != 1 {
			t.Errorf("GET %s recorded %d usage calls, want 1: the counter would go silent", ri.Path, len(calls))
		}
	}
	if seen == 0 {
		t.Fatal("no console data route found; this test would pass on nothing")
	}
}

// Counting is a measurement of the signed-in operator: a request that did not come through
// Authelia names nobody and is not counted, on the queue as on the page.
func TestAQueueRequestWithNoIdentityIsNotCounted(t *testing.T) {
	var calls []usageCall
	if w := serveUsage(t, recording(&calls, nil), "/console/queue", http.Header{}); w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if len(calls) != 0 {
		t.Fatalf("calls = %+v, want none", calls)
	}
}

// The counter is a measurement; a database that refuses the write never takes the page down.
func TestAFailedWriteStillServesThePage(t *testing.T) {
	var calls []usageCall
	w := serveUsage(t, recording(&calls, errors.New("down")), "/console/", http.Header{"Remote-User": {"operator"}})
	if w.Code != http.StatusOK || len(calls) != 1 {
		t.Fatalf("status = %d calls = %d, want 200 and one attempt", w.Code, len(calls))
	}
}
