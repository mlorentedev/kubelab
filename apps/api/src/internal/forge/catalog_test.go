package forge_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

type fakeLister struct {
	repos map[string][]string
	err   error
}

func (f *fakeLister) ListRepos(_ context.Context, owner string) ([]forge.Source, error) {
	if f.err != nil {
		return nil, f.err
	}
	var out []forge.Source
	for _, r := range f.repos[owner] {
		out = append(out, forge.Source{Forge: "github", Owner: owner, Repo: r})
	}
	return out, nil
}

func names(sources []forge.Source) []string {
	out := []string{}
	for _, s := range sources {
		out = append(out, s.String())
	}
	return out
}

func newCatalog(t *testing.T, decl string, l forge.Lister) *forge.Catalog {
	t.Helper()
	sources, err := forge.ParseSources(decl)
	if err != nil {
		t.Fatal(err)
	}
	return &forge.Catalog{Declared: sources, Listers: map[string]forge.Lister{"github": l}}
}

// A wildcard becomes the owner's repositories; a named source stays as declared,
// once, and the set is sorted so every consumer sees the same order.
func TestCatalogExpandsAnOwnersRepositories(t *testing.T) {
	l := &fakeLister{repos: map[string][]string{"o": {"b", "a"}}}
	c := newCatalog(t, "gitea:t/x,github:o/*,github:o/a", l)
	if err := c.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}
	want := []string{"gitea:t/x", "github:o/a", "github:o/b"}
	if got := names(c.Current()); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

// Before the first listing the named sources are already read.
func TestCatalogServesNamedSourcesBeforeAnyListing(t *testing.T) {
	c := newCatalog(t, "github:o/*,github:p/q", &fakeLister{})
	if got := names(c.Current()); !reflect.DeepEqual(got, []string{"github:p/q"}) {
		t.Fatalf("got %v", got)
	}
}

// A listing that fails keeps the last good set: a forge outage must not empty the
// view (AC1), and only a listing that succeeds may retire a repository.
func TestCatalogKeepsTheLastListingWhenOneFails(t *testing.T) {
	l := &fakeLister{repos: map[string][]string{"o": {"a", "b"}}}
	c := newCatalog(t, "github:o/*", l)
	if err := c.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}
	l.err = errors.New("down")
	if err := c.Resolve(context.Background()); err == nil {
		t.Fatal("a failed listing reported no error")
	}
	if got := names(c.Current()); !reflect.DeepEqual(got, []string{"github:o/a", "github:o/b"}) {
		t.Fatalf("after a failed listing: %v", got)
	}
	l.err, l.repos["o"] = nil, []string{"b"}
	if err := c.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := names(c.Current()); !reflect.DeepEqual(got, []string{"github:o/b"}) {
		t.Fatalf("a repository the listing dropped is still read: %v", got)
	}
}

// A lister answering for another owner widens nothing: the wildcard names its owner.
func TestCatalogAdmitsOnlyThePatternsOwner(t *testing.T) {
	l := listerFunc(func(context.Context, string) ([]forge.Source, error) {
		return []forge.Source{{Forge: "github", Owner: "o", Repo: "a"}, {Forge: "github", Owner: "org", Repo: "x"},
			{Forge: "gitea", Owner: "o", Repo: "y"}}, nil
	})
	c := newCatalog(t, "github:o/*", l)
	if err := c.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := names(c.Current()); !reflect.DeepEqual(got, []string{"github:o/a"}) {
		t.Fatalf("got %v", got)
	}
}

// A wildcard on a forge with no lister is an error, not a silent empty set.
func TestCatalogReportsAWildcardItCannotList(t *testing.T) {
	c := newCatalog(t, "gitea:t/*,github:p/q", &fakeLister{})
	if err := c.Resolve(context.Background()); err == nil {
		t.Fatal("no error for an unlistable wildcard")
	}
	if got := names(c.Current()); !reflect.DeepEqual(got, []string{"github:p/q"}) {
		t.Fatalf("got %v", got)
	}
}

type listerFunc func(context.Context, string) ([]forge.Source, error)

func (f listerFunc) ListRepos(ctx context.Context, owner string) ([]forge.Source, error) {
	return f(ctx, owner)
}

// The App's installation lists every repository it can read, across owners and
// including forks and archived ones; the owner's wildcard admits only its own
// live, original repositories, page after page.
func TestGitHubListsAnOwnersLiveRepositories(t *testing.T) {
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/installation/repositories" || r.Header.Get("Authorization") != "Bearer fresh" {
			http.Error(w, "unexpected "+r.URL.Path, http.StatusTeapot)
			return
		}
		repo := func(owner, name string, fork, archived bool) string {
			return fmt.Sprintf(`{"name":%q,"fork":%t,"archived":%t,"owner":{"login":%q}}`, name, fork, archived, owner)
		}
		if r.URL.Query().Get("page") == "" {
			w.Header().Set("Link", fmt.Sprintf(`<%s/installation/repositories?page=2>; rel="next"`, srv.URL))
			fmt.Fprintf(w, `{"total_count":4,"repositories":[%s,%s]}`,
				repo("O", "kubelab", false, false), repo("o", "a-fork", true, false))
			return
		}
		fmt.Fprintf(w, `{"total_count":4,"repositories":[%s,%s,%s]}`, repo("o", "old", false, true),
			repo("another", "x", false, false), repo("o", "ci-workflows", false, false))
	}))
	defer srv.Close()
	g := &forge.GitHub{BaseURL: srv.URL, Tokens: func(context.Context) (string, error) { return "fresh", nil }}
	got, err := g.ListRepos(context.Background(), "o")
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"github:O/kubelab", "github:o/ci-workflows"}; !reflect.DeepEqual(names(got), want) {
		t.Fatalf("got %v, want %v", names(got), want)
	}
}

// A failed page fails the listing: half a listing would retire the other half.
func TestGitHubListingFailsWhole(t *testing.T) {
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("page") == "" {
			w.Header().Set("Link", fmt.Sprintf(`<%s/installation/repositories?page=2>; rel="next"`, srv.URL))
			fmt.Fprint(w, `{"repositories":[{"name":"a","owner":{"login":"o"}}]}`)
			return
		}
		http.Error(w, "boom", http.StatusBadGateway)
	}))
	defer srv.Close()
	g := &forge.GitHub{BaseURL: srv.URL, Token: "t"}
	if got, err := g.ListRepos(context.Background(), "o"); err == nil {
		t.Fatalf("got %v and no error", names(got))
	}
}
