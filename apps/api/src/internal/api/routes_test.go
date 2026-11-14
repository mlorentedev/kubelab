package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

const machineToken = "test-machine-token"

func engine(t *testing.T) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	SetupRoutes(r, &ForgeView{CreateToken: machineToken, ConsoleDomain: "console.kubelab.live"})
	return r
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

// ADR-066 A2 and CONSOLE-004 AC2: no merge, no review submission, no reviewer request,
// no approval. Read from the engine the binary serves, not from a source file, so a route
// added anywhere is seen.
func TestNoRouteMergesReviewsOrRequestsAReviewer(t *testing.T) {
	forbidden := []string{"merge", "review", "approve", "approval", "requested_reviewers", "reviewer"}
	routes := engine(t).Routes()
	if len(routes) == 0 {
		t.Fatal("the engine has no routes; this test would pass on nothing")
	}
	for _, ri := range routes {
		path := strings.ToLower(ri.Path)
		for _, word := range forbidden {
			if strings.Contains(path, word) {
				t.Errorf("%s %s: a route that names %q exists", ri.Method, ri.Path, word)
			}
		}
	}
}

// AC3: the machine token is accepted on the create and grants nothing anywhere else. The
// property is "the same answer with the token as without it", on both hosts, so a route
// that would start honouring a Bearer is caught whatever it answers.
func TestTheMachineTokenGrantsOnlyTheCreate(t *testing.T) {
	r := engine(t)
	answer := func(method, path, host, auth string) int {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(method, path, strings.NewReader("{}"))
		req.Host = host
		if auth != "" {
			req.Header.Set("Authorization", auth)
		}
		r.ServeHTTP(w, req)
		return w.Code
	}
	sawCreate := false
	for _, ri := range r.Routes() {
		path := concrete(ri.Path)
		isCreate := ri.Method == http.MethodPost && ri.Path == "/api/forge/issues"
		sawCreate = sawCreate || isCreate
		for _, host := range []string{"api.kubelab.live", "console.kubelab.live"} {
			without := answer(ri.Method, path, host, "")
			with := answer(ri.Method, path, host, "Bearer "+machineToken)
			if isCreate {
				if without != http.StatusUnauthorized || with == http.StatusUnauthorized {
					t.Errorf("create on %s: %d without the token and %d with it", host, without, with)
				}
				continue
			}
			if with != without {
				t.Errorf("%s %s on %s: the token changed the answer from %d to %d", ri.Method, ri.Path, host, without, with)
			}
		}
	}
	if !sawCreate {
		t.Fatal("no POST /api/forge/issues route; n8n's create (CONSOLE-007) has nowhere to go")
	}
}

func TestTheCreateRefusesAWrongOrMalformedToken(t *testing.T) {
	r := engine(t)
	for _, auth := range []string{"Bearer wrong", "Bearer ", "Basic " + machineToken, machineToken, "bearer " + machineToken + "x"} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/forge/issues", strings.NewReader("{}"))
		req.Header.Set("Authorization", auth)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusUnauthorized {
			t.Errorf("Authorization %q: got %d, want 401", auth, w.Code)
		}
	}
}

// An api with no token declared accepts nobody, rather than an empty Bearer.
func TestTheCreateWithNoDeclaredTokenRefusesEveryone(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	SetupRoutes(r, &ForgeView{})
	for _, auth := range []string{"", "Bearer ", "Bearer x"} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/forge/issues", strings.NewReader("{}"))
		if auth != "" {
			req.Header.Set("Authorization", auth)
		}
		r.ServeHTTP(w, req)
		if w.Code != http.StatusUnauthorized {
			t.Errorf("Authorization %q with no declared token: got %d, want 401", auth, w.Code)
		}
	}
}
