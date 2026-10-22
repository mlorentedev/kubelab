package forge_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// runReaderContract holds every adapter to the same behaviour, so a new forge
// is one constructor and one recorded fixture away from the guarantees below.
func runReaderContract(t *testing.T, forgeName, fixture string, newReader func(baseURL string) forge.Reader) {
	t.Helper()
	body, err := os.ReadFile("testdata/" + fixture)
	if err != nil {
		t.Fatal(err)
	}
	src := forge.Source{Forge: forgeName, Owner: "mlorentedev", Repo: "kubelab"}

	t.Run("maps a recorded response to neutral items", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(body)
		}))
		defer srv.Close()

		items, err := newReader(srv.URL).ListItems(context.Background(), src, time.Time{})
		if err != nil {
			t.Fatal(err)
		}
		if len(items) != 3 {
			t.Fatalf("want 3 items, got %d", len(items))
		}
		byNumber := map[int]forge.Item{}
		for _, it := range items {
			byNumber[it.Number] = it
		}
		issue, pull := byNumber[2570], byNumber[2623]
		if issue.Kind != forge.KindIssue || pull.Kind != forge.KindPull {
			t.Fatalf("kinds: issue=%q pull=%q", issue.Kind, pull.Kind)
		}
		if issue.State != "open" || issue.Author == "" || issue.Title == "" || issue.URL == "" {
			t.Fatalf("incomplete issue: %+v", issue)
		}
		if len(issue.Assignees) != 1 || len(issue.Labels) != 2 {
			t.Fatalf("assignees/labels: %+v", issue)
		}
		if issue.UpdatedAt.IsZero() || issue.Source != src {
			t.Fatalf("source or time missing: %+v", issue)
		}
	})

	t.Run("a source that is down is an error naming the source, never an empty list", func(t *testing.T) {
		srv := httptest.NewServer(http.NotFoundHandler())
		url := srv.URL
		srv.Close()

		items, err := newReader(url).ListItems(context.Background(), src, time.Time{})
		var se *forge.SourceError
		if !errors.As(err, &se) || se.Source != src {
			t.Fatalf("want a SourceError for %v, got %v", src, err)
		}
		if items != nil {
			t.Fatalf("an unreachable source returned items: %v", items)
		}
	})

	t.Run("a non-2xx answer is an error naming the source", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			http.Error(w, "rate limited", http.StatusForbidden)
		}))
		defer srv.Close()

		_, err := newReader(srv.URL).ListItems(context.Background(), src, time.Time{})
		var se *forge.SourceError
		if !errors.As(err, &se) {
			t.Fatalf("want a SourceError, got %v", err)
		}
	})
}

func TestGitHubReader(t *testing.T) {
	runReaderContract(t, "github", "github_issues.json", func(baseURL string) forge.Reader {
		return &forge.GitHub{BaseURL: baseURL}
	})
}

func TestGitHubReaderFollowsPagesAndSendsSince(t *testing.T) {
	body, _ := os.ReadFile("testdata/github_issues.json")
	var sawSince string
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("page") == "2" {
			_, _ = w.Write([]byte("[]"))
			return
		}
		sawSince = r.URL.Query().Get("since")
		w.Header().Set("Link", `<`+srv.URL+r.URL.Path+`?page=2>; rel="next"`)
		_, _ = w.Write(body)
	}))
	defer srv.Close()

	since := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	items, err := (&forge.GitHub{BaseURL: srv.URL}).ListItems(context.Background(),
		forge.Source{Forge: "github", Owner: "o", Repo: "r"}, since)
	if err != nil || len(items) != 3 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	if sawSince != "2026-10-01T00:00:00Z" {
		t.Fatalf("since was %q", sawSince)
	}
}

func TestGitHubReaderSendsTheTokenOnlyWhenSet(t *testing.T) {
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		_, _ = w.Write([]byte("[]"))
	}))
	defer srv.Close()
	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}

	_, _ = (&forge.GitHub{BaseURL: srv.URL}).ListItems(context.Background(), src, time.Time{})
	if auth != "" {
		t.Fatalf("sent %q without a token", auth)
	}
	_, _ = (&forge.GitHub{BaseURL: srv.URL, Token: "t"}).ListItems(context.Background(), src, time.Time{})
	if auth != "Bearer t" {
		t.Fatalf("sent %q", auth)
	}
}

func TestGitHubReaderNeverFollowsAPageOffItsHost(t *testing.T) {
	var elsewhere int
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		elsewhere++
		_, _ = w.Write([]byte("[]"))
	}))
	defer other.Close()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Link", `<`+other.URL+`/steal>; rel="next"`)
		_, _ = w.Write([]byte("[]"))
	}))
	defer srv.Close()

	_, err := (&forge.GitHub{BaseURL: srv.URL, Token: "t"}).ListItems(context.Background(),
		forge.Source{Forge: "github", Owner: "o", Repo: "r"}, time.Time{})
	var se *forge.SourceError
	if !errors.As(err, &se) {
		t.Fatalf("want a SourceError, got %v", err)
	}
	if elsewhere != 0 {
		t.Fatalf("the reader followed a next link to another host %d time(s)", elsewhere)
	}
}

func TestGitHubReaderStopsAtThePageCap(t *testing.T) {
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Link", `<`+srv.URL+r.URL.Path+`>; rel="next"`)
		_, _ = w.Write([]byte("[]"))
	}))
	defer srv.Close()

	_, err := (&forge.GitHub{BaseURL: srv.URL}).ListItems(context.Background(),
		forge.Source{Forge: "github", Owner: "o", Repo: "r"}, time.Time{})
	var se *forge.SourceError
	if !errors.As(err, &se) {
		t.Fatalf("an endless listing must end in a SourceError, got %v", err)
	}
}
