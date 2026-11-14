package console

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

func consoleEngine(t *testing.T) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	declared, err := forge.ParseSources("gitea:personal/*")
	if err != nil {
		t.Fatal(err)
	}
	Register(r, func() (QueueReader, []forge.Source, error) { return &fakeQueue{}, declared, nil },
		func() string { return consoleHost }, nil)
	return r
}

// writeRoutes is every route Register adds that is not a GET: the writes.
func writeRoutes(r *gin.Engine) []gin.RouteInfo {
	var out []gin.RouteInfo
	for _, ri := range r.Routes() {
		if ri.Method != http.MethodGet && ri.Method != http.MethodHead {
			out = append(out, ri)
		}
	}
	return out
}

// concrete fills a route's parameters, so the request matches it.
func concrete(path string) string {
	parts := strings.Split(path, "/")
	for i, p := range parts {
		if strings.HasPrefix(p, ":") || strings.HasPrefix(p, "*") {
			parts[i] = "x1"
		}
	}
	return strings.Join(parts, "/")
}

func TestConsoleRegistersTheNarrowWrites(t *testing.T) {
	if n := len(writeRoutes(consoleEngine(t))); n == 0 {
		t.Fatal("no write route registered; the 401 test below would pass on nothing")
	}
}

// The browser never sees this 401: Authelia answers before the pod for a request with no
// session. This is the pod's own guard for a request that reaches it without the header
// Authelia sets, from inside the cluster for instance, since the host check alone can be
// satisfied by anyone who can reach the Service.
func TestEveryConsoleWriteAnswers401WithoutAnAutheliaIdentity(t *testing.T) {
	r := consoleEngine(t)
	for _, ri := range writeRoutes(r) {
		for _, user := range []string{"", "   "} {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(ri.Method, concrete(ri.Path), strings.NewReader("{}"))
			req.Host = consoleHost
			if user != "" {
				req.Header.Set("Remote-User", user)
			}
			r.ServeHTTP(w, req)
			if w.Code != http.StatusUnauthorized {
				t.Errorf("%s %s with Remote-User %q: got %d, want 401", ri.Method, ri.Path, user, w.Code)
			}
		}
	}
}

func TestAConsoleWriteWithAnIdentityReachesItsHandler(t *testing.T) {
	r := consoleEngine(t)
	for _, ri := range writeRoutes(r) {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(ri.Method, concrete(ri.Path), strings.NewReader("{}"))
		req.Host = consoleHost
		req.Header.Set("Remote-User", "operator")
		r.ServeHTTP(w, req)
		if w.Code == http.StatusUnauthorized || w.Code == http.StatusNotFound {
			t.Errorf("%s %s with an identity: got %d, the guard refused it", ri.Method, ri.Path, w.Code)
		}
	}
}

func TestConsoleWritesAreNotServedOnTheApiHost(t *testing.T) {
	r := consoleEngine(t)
	for _, ri := range writeRoutes(r) {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(ri.Method, concrete(ri.Path), strings.NewReader("{}"))
		req.Host = "api.kubelab.live"
		req.Header.Set("Remote-User", "operator")
		r.ServeHTTP(w, req)
		if w.Code != http.StatusNotFound {
			t.Errorf("%s %s on the api host: got %d, want 404", ri.Method, ri.Path, w.Code)
		}
	}
}
