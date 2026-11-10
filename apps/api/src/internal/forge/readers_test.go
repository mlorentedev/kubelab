package forge_test

import (
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

// The ceiling is per forge (AC4): GitHub's calls must not spend Gitea's hour.
func TestEachForgeHasItsOwnCeiling(t *testing.T) {
	readers := forge.NewReaders(forge.Credentials{GiteaURL: "http://gitea:3000"})
	gh, gt := readers["github"].(*forge.GitHub), readers["gitea"].(*forge.Gitea)
	if gh.HTTP == nil || gt.HTTP == nil || gh.HTTP.Transport == gt.HTTP.Transport {
		t.Error("the two forges share one call ceiling")
	}
}
