package forge_test

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// A gitea: source with no reader reads as "no reader for this forge" forever, so
// a reader is wired whenever the environment names the forge's address.
func TestTheGiteaReaderIsWiredWhenItsAddressIsDeclared(t *testing.T) {
	c := forge.Credentials{GiteaURL: "http://gitea:3000", GiteaToken: "token"}
	readers := forge.NewReaders(c)
	gitea, ok := readers["gitea"].(*forge.Gitea)
	if !ok {
		t.Fatalf("no gitea reader in %v", readers)
	}
	if gitea.BaseURL != c.GiteaURL || gitea.Token != c.GiteaToken {
		t.Errorf("gitea reader got %q, token set %v", gitea.BaseURL, gitea.Token != "")
	}
	if _, ok := readers["github"]; !ok {
		t.Error("the github reader is gone")
	}
}

// Staging has no Gitea: without an address there is no reader, rather than calls
// to a host that is not there.
func TestNoGiteaReaderWithoutAnAddress(t *testing.T) {
	if _, ok := forge.NewReaders(forge.Credentials{})["gitea"]; ok {
		t.Error("a gitea reader with no address")
	}
}

// The ceiling is per forge (AC4): spending Gitea's whole hour leaves GitHub's untouched.
func TestEachForgeHasItsOwnCeiling(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer srv.Close()
	readers := forge.NewReaders(forge.Credentials{GiteaURL: srv.URL})
	call := func(c *http.Client) error {
		req, _ := http.NewRequest(http.MethodGet, srv.URL, nil)
		resp, err := c.Transport.RoundTrip(req)
		if err == nil {
			resp.Body.Close()
		}
		return err
	}
	gitea, github := readers["gitea"].(*forge.Gitea).HTTP, readers["github"].(*forge.GitHub).HTTP
	for i := 0; i < forge.HourlyCallCeiling; i++ {
		if err := call(gitea); err != nil {
			t.Fatalf("gitea call %d: %v", i, err)
		}
	}
	if err := call(gitea); !errors.Is(err, forge.ErrCeiling) {
		t.Fatalf("gitea past its ceiling: got %v, want ErrCeiling", err)
	}
	if err := call(github); err != nil {
		t.Errorf("github refused after gitea spent its hour: %v", err)
	}
}

// Listing and reading share one GitHub client, so they spend one hourly ceiling (AC4).
func TestTheGitHubListerIsTheGitHubReader(t *testing.T) {
	readers := forge.NewReaders(forge.Credentials{GiteaURL: "http://gitea:3000"})
	listers := forge.Listers(readers)
	if readers["github"] == nil || any(listers["github"]) != any(readers["github"]) {
		t.Fatalf("github lister %v is not the reader %v", listers["github"], readers["github"])
	}
	if _, ok := listers["gitea"]; ok {
		t.Error("gitea lists nothing yet; a lister there would answer for repositories it cannot list")
	}
}
