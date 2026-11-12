package console

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
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

// The queue is polled by the open page, so counting it would count refreshes, not visits.
func TestTheQueueIsNotCounted(t *testing.T) {
	var calls []usageCall
	serveUsage(t, recording(&calls, nil), "/console/queue", http.Header{"Remote-User": {"operator"}})
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
