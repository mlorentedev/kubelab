package health

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

func fullConfig() *config.Config {
	c := &config.Config{Version: "1.2.3"}
	c.Beehiiv.APIKey = "key"
	c.Beehiiv.PubID = "pub_1"
	c.Email.Host, c.Email.User, c.Email.Pass = "smtp", "u", "p"
	return c
}

// newHandler returns a Handler with a fake Beehiiv at the returned URL and a
// controllable clock. hits counts requests that reached the fake.
func newHandler(t *testing.T, beehiivStatus int, cfg *config.Config, cfgErr error) (*Handler, *int32, *time.Time) {
	t.Helper()
	var hits int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.WriteHeader(beehiivStatus)
	}))
	t.Cleanup(srv.Close)
	now := time.Unix(1_700_000_000, 0)
	h := &Handler{
		LoadConfig:  func() (*config.Config, error) { return cfg, cfgErr },
		HTTPClient:  srv.Client(),
		BeehiivBase: srv.URL,
		Now:         func() time.Time { return now },
	}
	return h, &hits, &now
}

func get(t *testing.T, h *Handler, path string) (int, Response) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h.Register(r)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
	var body Response
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("%s: body is not JSON: %v", path, err)
	}
	return w.Code, body
}

func TestLivenessNeverTouchesDependencies(t *testing.T) {
	h, hits, _ := newHandler(t, 500, nil, errors.New("config broken"))
	for _, p := range []string{"/health", "/healthz"} {
		code, body := get(t, h, p)
		if code != 200 || body.Status != StatusAlive || body.Service != "kubelab-api" {
			t.Fatalf("%s = %d %+v, want 200 alive kubelab-api", p, code, body)
		}
	}
	if *hits != 0 {
		t.Fatalf("liveness reached Beehiiv %d times", *hits)
	}
}

func TestReadyIs503WhenConfigDoesNotLoad(t *testing.T) {
	h, _, _ := newHandler(t, 200, nil, errors.New("missing env"))
	code, body := get(t, h, "/ready")
	if code != 503 || body.Status != StatusUnready {
		t.Fatalf("/ready = %d %+v, want 503 unready", code, body)
	}
}

func TestReadyIsHealthyWhenEverythingWorks(t *testing.T) {
	h, _, _ := newHandler(t, 200, fullConfig(), nil)
	code, body := get(t, h, "/ready")
	if code != 200 || body.Status != StatusReady || body.Version != "1.2.3" {
		t.Fatalf("/ready = %d %+v, want 200 ready 1.2.3", code, body)
	}
}

func TestBeehiivDownIsDegradedNotUnready(t *testing.T) {
	h, _, _ := newHandler(t, 503, fullConfig(), nil)
	code, body := get(t, h, "/ready")
	if code != 200 || body.Status != StatusDegraded {
		t.Fatalf("/ready = %d %+v, want 200 degraded", code, body)
	}
	if body.Checks[0].Component != "beehiiv" || body.Checks[0].Status != checkDegraded {
		t.Fatalf("beehiiv check = %+v, want degraded", body.Checks[0])
	}
}

func TestBeehiivUnreachableIsDegraded(t *testing.T) {
	h, _, _ := newHandler(t, 200, fullConfig(), nil)
	h.BeehiivBase = "http://127.0.0.1:1" // nothing listens
	code, body := get(t, h, "/ready")
	if code != 200 || body.Status != StatusDegraded {
		t.Fatalf("/ready = %d %+v, want 200 degraded", code, body)
	}
}

func TestMissingEmailConfigIsDegraded(t *testing.T) {
	cfg := fullConfig()
	cfg.Email.Pass = ""
	h, _, _ := newHandler(t, 200, cfg, nil)
	code, body := get(t, h, "/ready")
	if code != 200 || body.Status != StatusDegraded {
		t.Fatalf("/ready = %d %+v, want 200 degraded", code, body)
	}
}

func TestBeehiivRoundTripIsCached(t *testing.T) {
	h, hits, now := newHandler(t, 200, fullConfig(), nil)
	get(t, h, "/ready")
	get(t, h, "/ready")
	if *hits != 1 {
		t.Fatalf("hits within TTL = %d, want 1", *hits)
	}
	*now = now.Add(beehiivCacheTTL + time.Second)
	get(t, h, "/ready")
	if *hits != 2 {
		t.Fatalf("hits after TTL = %d, want 2", *hits)
	}
}

func TestSlowBeehiivDoesNotQueueProbes(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-release }))
	t.Cleanup(func() { close(release); srv.Close() })
	now := time.Unix(1_700_000_000, 0)
	h := &Handler{
		LoadConfig:  func() (*config.Config, error) { return fullConfig(), nil },
		HTTPClient:  srv.Client(),
		BeehiivBase: srv.URL,
		Now:         func() time.Time { return now },
	}
	first := make(chan struct{})
	go func() { get(t, h, "/ready"); close(first) }()
	for i := 0; i < 200; i++ { // wait until the first probe is in flight
		h.mu.Lock()
		busy := h.refreshing
		h.mu.Unlock()
		if busy {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	done := make(chan Response, 1)
	go func() { _, b := get(t, h, "/ready"); done <- b }()
	select {
	case b := <-done:
		if b.Status != StatusDegraded {
			t.Fatalf("status while first probe pending = %q, want degraded", b.Status)
		}
	case <-time.After(time.Second):
		t.Fatal("second /ready blocked behind the in-flight Beehiiv probe")
	}
}

// A prober that gives up mid-request (kubelet aborts at timeoutSeconds, shorter
// than the Beehiiv timeout) must not leave its own cancellation as the cached
// verdict for the next 30s: the probe measures Beehiiv, not the caller's patience.
func TestAbortedProberDoesNotPoisonTheCache(t *testing.T) {
	h, hits, _ := newHandler(t, 200, fullConfig(), nil)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h.Register(r)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // the prober has already hung up
	r.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/ready", nil).WithContext(ctx))

	code, body := get(t, h, "/ready")
	if code != http.StatusOK || body.Status != StatusReady {
		t.Fatalf("after an aborted prober: %d %q, want 200 %q (Beehiiv is healthy)", code, body.Status, StatusReady)
	}
	if *hits != 1 {
		t.Fatalf("hits = %d, want 1 (the aborted probe's verdict is the cached one)", *hits)
	}
}

func withPostgres(c *config.Config) *config.Config {
	c.Postgres = config.Postgres{Host: "postgres", Port: "5432", Tenant: "api"}
	c.Postgres.Password = strings.Repeat("x", 8) // built at run time: not a credential
	return c
}

func postgresChecks(r Response) []Check {
	var out []Check
	for _, ck := range r.Checks {
		if ck.Component == "postgres" {
			out = append(out, ck)
		}
	}
	return out
}

func TestReadyReportsPostgresOK(t *testing.T) {
	h, _, _ := newHandler(t, http.StatusOK, withPostgres(fullConfig()), nil)
	h.PingPostgres = func(context.Context, *config.Config) error { return nil }

	code, resp := get(t, h, "/ready")
	got := postgresChecks(resp)
	if code != http.StatusOK || resp.Status != StatusReady || len(got) != 1 || got[0].Status != checkOK {
		t.Fatalf("code %d status %q postgres %+v", code, resp.Status, got)
	}
}

// A database outage degrades the API but never takes it out of rotation, and the driver's error,
// which can carry connection details, does not reach the response.
func TestReadyDegradesWithoutGatingWhenPostgresIsDown(t *testing.T) {
	h, _, _ := newHandler(t, http.StatusOK, withPostgres(fullConfig()), nil)
	h.PingPostgres = func(context.Context, *config.Config) error { return errors.New("dial failed: driver detail") }

	code, resp := get(t, h, "/ready")
	got := postgresChecks(resp)
	if code != http.StatusOK || resp.Status != StatusDegraded || len(got) != 1 {
		t.Fatalf("code %d status %q postgres %+v", code, resp.Status, got)
	}
	if got[0].Message != "postgres unreachable" {
		t.Fatalf("message leaks the driver error: %q", got[0].Message)
	}
}

func TestReadyOmitsPostgresWhereItIsNotConfigured(t *testing.T) {
	h, _, _ := newHandler(t, http.StatusOK, fullConfig(), nil)
	h.PingPostgres = func(context.Context, *config.Config) error {
		t.Fatal("must not ping an unconfigured database")
		return nil
	}

	code, resp := get(t, h, "/ready")
	if code != http.StatusOK || resp.Status != StatusReady || len(postgresChecks(resp)) != 0 {
		t.Fatalf("code %d status %q checks %+v", code, resp.Status, resp.Checks)
	}
}
