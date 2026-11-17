package forge_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"sort"
	"strings"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The set of actions is the outbox's CHECK, read from the migration: a writer that learns an
// action the table refuses (or the table gains one the writer cannot make) is red here. The
// closed set is also what keeps a merge, a review or a reviewer request out of the writer
// (routes_test.go holds the routes to the same list).
func TestTheActionsAreTheOutboxCheckList(t *testing.T) {
	raw, err := os.ReadFile("../../../migrations/20261116000000_forge_write_outbox.sql")
	if err != nil {
		t.Fatal(err)
	}
	block := regexp.MustCompile(`(?s)action\s+text\s+NOT NULL CHECK \(action IN \((.*?)\)\)`).FindStringSubmatch(string(raw))
	if block == nil {
		t.Fatal("the outbox's action CHECK is not where this test reads it")
	}
	var want, got []string
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllStringSubmatch(block[1], -1) {
		want = append(want, m[1])
	}
	for _, a := range forge.Actions {
		got = append(got, string(a))
	}
	sort.Strings(want)
	sort.Strings(got)
	if strings.Join(got, ",") != strings.Join(want, ",") || len(want) != 7 {
		t.Fatalf("writer actions %v, outbox CHECK %v", got, want)
	}
}

func TestMarker(t *testing.T) {
	if got := forge.Marker(42); got != "<!-- kubelab-write:42 -->" {
		t.Fatalf("marker %q", got)
	}
}

// Staging's shape (W7): the reader has an address and a read token, and there is no write token.
// It has no Gitea writer, and the read token is never lent to a write.
func TestNoGiteaWriterWithoutAWriteToken(t *testing.T) {
	writers := forge.NewWriters(forge.Credentials{GiteaURL: "http://gitea:3000", GiteaToken: "read-token"})
	if _, ok := writers["gitea"]; ok {
		t.Fatal("a gitea writer was built from the read token")
	}
	w, err := forge.WriterFor(writers, "gitea")
	if w != nil || !errors.Is(err, forge.ErrNoWriter) {
		t.Fatalf("got %v, %v; want ErrNoWriter", w, err)
	}
}

func TestNoGiteaWriterWithoutAnAddress(t *testing.T) {
	if _, ok := forge.NewWriters(forge.Credentials{GiteaWriteToken: "w"})["gitea"]; ok {
		t.Fatal("a gitea writer with no address")
	}
}

func TestTheGiteaWriterIsWiredFromItsOwnToken(t *testing.T) {
	c := forge.Credentials{GiteaURL: "http://gitea:3000", GiteaToken: "read-token", GiteaWriteToken: "write-token"}
	w, err := forge.WriterFor(forge.NewWriters(c), "gitea")
	if err != nil {
		t.Fatal(err)
	}
	gitea, ok := w.(*forge.GiteaWriter)
	if !ok || gitea.BaseURL != c.GiteaURL || gitea.Token != "write-token" {
		t.Fatalf("got %#v", w)
	}
}

// The Gitea writer sends its own token and never the reader's.
func TestTheGiteaWriterNeverSendsTheReadToken(t *testing.T) {
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		_, _ = w.Write([]byte(`{"state":"closed"}`))
	}))
	defer srv.Close()
	w, err := forge.WriterFor(forge.NewWriters(forge.Credentials{GiteaURL: srv.URL, GiteaToken: "read-token", GiteaWriteToken: "write-token"}), "gitea")
	if err != nil {
		t.Fatal(err)
	}
	got := w.Write(context.Background(), forge.Write{Action: forge.ActionClose, Source: gtSrc, Number: 1})
	if got.Outcome != forge.OutcomeApplied || auth != "token write-token" {
		t.Fatalf("%+v, sent %q", got, auth)
	}
}

// GitHub writes through the App installation: without the App key it has no writer, and a
// write is never sent anonymously.
func TestNoGitHubWriterWithoutTheAppKey(t *testing.T) {
	writers := forge.NewWriters(forge.Credentials{GitHubAppID: "1", GitHubInstallationID: "2"})
	if _, ok := writers["github"]; ok {
		t.Fatal("a github writer with no App key")
	}
	if _, err := forge.WriterFor(writers, "github"); !errors.Is(err, forge.ErrNoWriter) {
		t.Fatalf("got %v", err)
	}
}

func TestTheGitHubWriterUsesTheAppInstallationToken(t *testing.T) {
	w, err := forge.WriterFor(forge.NewWriters(forge.Credentials{
		GitHubAppID: "1", GitHubInstallationID: "2", GitHubPrivateKey: "pem",
	}), "github")
	if err != nil {
		t.Fatal(err)
	}
	gh, ok := w.(*forge.GitHubWriter)
	if !ok || gh.Tokens == nil || gh.Token != "" || gh.BaseURL != "https://api.github.com" {
		t.Fatalf("got %#v", w)
	}
}

func TestWriterForAnUnknownForge(t *testing.T) {
	if _, err := forge.WriterFor(forge.NewWriters(forge.Credentials{}), "bitbucket"); !errors.Is(err, forge.ErrNoWriter) {
		t.Fatalf("got %v", err)
	}
}

// Writes have a call ceiling of their own (AC4), so a reconcile that spends the reader's hour
// does not refuse an operator's click, and the other way round.
func TestEachWriterHasItsOwnCeiling(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer srv.Close()
	c := forge.Credentials{GiteaURL: srv.URL, GiteaToken: "r", GiteaWriteToken: "w", GitHubPrivateKey: "pem"}
	writers := forge.NewWriters(c)
	readers := forge.NewReaders(c)

	gitea := writers["gitea"].(*forge.GiteaWriter).HTTP
	github := writers["github"].(*forge.GitHubWriter).HTTP
	if gitea == github || gitea == readers["gitea"].(*forge.Gitea).HTTP || github == readers["github"].(*forge.GitHub).HTTP {
		t.Fatal("a writer shares an HTTP client, and so a ceiling, with another forge or with a reader")
	}
	for name, client := range map[string]*http.Client{"gitea": gitea, "github": github} {
		ceiling, ok := client.Transport.(*forge.Ceiling)
		if !ok || ceiling.Limit != forge.HourlyCallCeiling {
			t.Errorf("%s writer transport %T has no hourly ceiling", name, client.Transport)
		}
	}
}
