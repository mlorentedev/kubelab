package forge_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// wantItem is what one recorded item must map to.
type wantItem struct {
	Number    int
	Kind      forge.Kind
	State     string
	Assignees int
	Labels    int
}

// readerContract is everything that differs between forges: the request every
// listing must make, the recorded answer, and the items that answer must map to.
type readerContract struct {
	Forge string
	// Path and Query are what every listing must request. Dropping state=all
	// would hide every closed item, so the contract pins them.
	Path  string
	Query url.Values
	// Recorded answers one listing from a recorded fixture.
	Recorded http.HandlerFunc
	New      func(baseURL string) forge.Reader
	Count    int
	Items    []wantItem
}

// runReaderContract holds every adapter to the same behaviour, so a new forge
// is one constructor, one recorded fixture and one table of expectations away
// from the guarantees below.
func runReaderContract(t *testing.T, c readerContract) {
	t.Helper()
	src := forge.Source{Forge: c.Forge, Owner: "o", Repo: "r"}

	t.Run("maps a recorded response to neutral items", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != c.Path {
				t.Errorf("requested %s, want %s", r.URL.Path, c.Path)
			}
			for k, want := range c.Query {
				if got := r.URL.Query()[k]; len(got) != 1 || got[0] != want[0] {
					t.Errorf("query %s=%v, want %v", k, got, want)
				}
			}
			w.Header().Set("Content-Type", "application/json")
			c.Recorded(w, r)
		}))
		defer srv.Close()

		items, err := c.New(srv.URL).ListItems(context.Background(), src, time.Time{})
		if err != nil {
			t.Fatal(err)
		}
		if len(items) != c.Count {
			t.Fatalf("want %d items, got %d", c.Count, len(items))
		}
		byNumber := map[int]forge.Item{}
		for _, it := range items {
			byNumber[it.Number] = it
		}
		for _, want := range c.Items {
			got, ok := byNumber[want.Number]
			if !ok {
				t.Fatalf("item %d missing", want.Number)
			}
			if got.Kind != want.Kind || got.State != want.State {
				t.Fatalf("item %d: kind=%q state=%q, want %q/%q", want.Number, got.Kind, got.State, want.Kind, want.State)
			}
			if len(got.Assignees) != want.Assignees || len(got.Labels) != want.Labels {
				t.Fatalf("item %d: assignees=%v labels=%v", want.Number, got.Assignees, got.Labels)
			}
			if got.Author == "" || got.Title == "" || got.URL == "" || got.UpdatedAt.IsZero() || got.Source != src {
				t.Fatalf("item %d incomplete: %+v", want.Number, got)
			}
		}
	})

	t.Run("a source that is down is an error naming the source, never an empty list", func(t *testing.T) {
		srv := httptest.NewServer(http.NotFoundHandler())
		url := srv.URL
		srv.Close()

		items, err := c.New(url).ListItems(context.Background(), src, time.Time{})
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

		_, err := c.New(srv.URL).ListItems(context.Background(), src, time.Time{})
		var se *forge.SourceError
		if !errors.As(err, &se) {
			t.Fatalf("want a SourceError, got %v", err)
		}
	})
}

func fixture(t *testing.T, name string) []byte {
	t.Helper()
	body, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func TestGitHubReader(t *testing.T) {
	body := fixture(t, "github_issues.json")
	runReaderContract(t, readerContract{
		Forge: "github",
		Path:  "/repos/o/r/issues",
		Query: url.Values{"state": {"all"}, "per_page": {"100"}},
		Recorded: func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write(body)
		},
		New:   func(baseURL string) forge.Reader { return &forge.GitHub{BaseURL: baseURL} },
		Count: 3,
		Items: []wantItem{
			{Number: 2570, Kind: forge.KindIssue, State: "open", Assignees: 1, Labels: 2},
			{Number: 2623, Kind: forge.KindPull, State: "open", Assignees: 0, Labels: 1},
		},
	})
}

func TestGiteaReader(t *testing.T) {
	issues, pulls := fixture(t, "gitea_issues.json"), fixture(t, "gitea_pulls.json")
	runReaderContract(t, readerContract{
		Forge: "gitea",
		Path:  "/api/v1/repos/o/r/issues",
		Query: url.Values{"state": {"all"}, "limit": {"50"}},
		// Gitea lists issues and pull requests apart, so the recording does too.
		Recorded: func(w http.ResponseWriter, r *http.Request) {
			switch r.URL.Query().Get("type") {
			case "issues":
				_, _ = w.Write(issues)
			case "pulls":
				_, _ = w.Write(pulls)
			default:
				http.Error(w, "type must be issues or pulls", http.StatusBadRequest)
			}
		},
		New:   func(baseURL string) forge.Reader { return &forge.Gitea{BaseURL: baseURL} },
		Count: 4,
		Items: []wantItem{
			{Number: 724, Kind: forge.KindIssue, State: "open", Assignees: 0, Labels: 1},
			{Number: 714, Kind: forge.KindIssue, State: "closed", Assignees: 1, Labels: 0},
			{Number: 728, Kind: forge.KindPull, State: "open"},
			{Number: 727, Kind: forge.KindPull, State: "closed"},
		},
	})
}

func TestGiteaReaderFailsWhenEitherListingFails(t *testing.T) {
	issues := fixture(t, "gitea_issues.json")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("type") == "pulls" {
			http.Error(w, "boom", http.StatusInternalServerError)
			return
		}
		_, _ = w.Write(issues)
	}))
	defer srv.Close()

	items, err := (&forge.Gitea{BaseURL: srv.URL}).ListItems(context.Background(),
		forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}, time.Time{})
	var se *forge.SourceError
	if !errors.As(err, &se) || items != nil {
		t.Fatalf("half a repository must not read as a repository: items=%v err=%v", items, err)
	}
}

func TestGiteaReaderSendsSinceAndTheTokenOnlyWhenSet(t *testing.T) {
	var since, auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		since, auth = r.URL.Query().Get("since"), r.Header.Get("Authorization")
		_, _ = w.Write([]byte("[]"))
	}))
	defer srv.Close()
	src := forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}

	_, _ = (&forge.Gitea{BaseURL: srv.URL}).ListItems(context.Background(), src,
		time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC))
	if auth != "" || since != "2026-10-01T00:00:00Z" {
		t.Fatalf("auth=%q since=%q", auth, since)
	}
	_, _ = (&forge.Gitea{BaseURL: srv.URL, Token: "t"}).ListItems(context.Background(), src, time.Time{})
	if auth != "token t" {
		t.Fatalf("sent %q", auth)
	}
}

func TestGitHubReaderFollowsPagesAndSendsSince(t *testing.T) {
	body := fixture(t, "github_issues.json")
	var sawSince string
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("page") == "2" {
			_, _ = w.Write([]byte(`[{"number":9001,"title":"second page","state":"open","html_url":"u","updated_at":"2026-10-02T00:00:00Z","user":{"login":"a"}}]`))
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
	if err != nil || len(items) != 4 {
		t.Fatalf("want the 3 first-page items and the 1 second-page item, got %d (err=%v)", len(items), err)
	}
	if last := items[len(items)-1]; last.Number != 9001 {
		t.Fatalf("the second page was not read last: %+v", last)
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
