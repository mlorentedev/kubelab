package forge_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// ADR-066 W4 and W8: a create whose outcome is unknown is resolved by finding the issue that
// carries its marker. "Not found" is what lets the worker post again, so it must be
// authoritative: it comes from a listing of everything since the create was sent, matched on the
// whole marker, never from a search index that can lag, and a page that cannot be read, or a
// listing that does not end, is an error and never a "not found".

type lookupContract struct {
	Name string
	Src  forge.Source
	// New builds the adapter with an injected clock.
	New func(baseURL string, now func() time.Time) forge.Writer
	// Path and Query are what the listing must request.
	Path  string
	Query url.Values
	// Pull marks an item as a pull request in the forge's own listing shape; empty when the
	// listing cannot hold one.
	Pull string
}

func lookupItem(number int, body, extra string) string {
	return fmt.Sprintf(`{"number":%d,"html_url":"https://forge.example/o/r/issues/%d","body":%q%s}`, number, number, body, extra)
}

func listing(items ...string) string { return "[" + strings.Join(items, ",") + "]" }

func runLookupContract(t *testing.T, c lookupContract) {
	t.Helper()
	sent := time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)
	settle := 90 * time.Second
	q := func(id int64) forge.Lookup {
		return forge.Lookup{Source: c.Src, OutboxID: id, SentAt: sent, Settle: settle}
	}
	serve := func(t *testing.T, h http.HandlerFunc) *httptest.Server {
		srv := httptest.NewServer(h)
		t.Cleanup(srv.Close)
		return srv
	}
	afterSettle := func() time.Time { return sent.Add(settle + time.Second) }

	t.Run("asks for every issue since the create was sent, in the listing's own shape", func(t *testing.T) {
		var seen *http.Request
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
			seen = r.Clone(context.Background())
			_, _ = w.Write([]byte(listing()))
		})
		if _, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42)); err != nil {
			t.Fatal(err)
		}
		if seen.Method != http.MethodGet || seen.URL.Path != c.Path {
			t.Fatalf("%s %s, want GET %s", seen.Method, seen.URL.Path, c.Path)
		}
		for k, want := range c.Query {
			if got := seen.URL.Query()[k]; len(got) != 1 || got[0] != want[0] {
				t.Errorf("query %s=%v, want %v", k, got, want)
			}
		}
		// The bound is when the create was sent, less a margin for the clocks of the two ends: the
		// forge's `since` is an updated-after filter, and an issue is updated no earlier than created.
		since, err := time.Parse(time.RFC3339, seen.URL.Query().Get("since"))
		if err != nil || since.After(sent) || sent.Sub(since) > time.Hour {
			t.Errorf("since=%q is not a bound just before %s", seen.URL.Query().Get("since"), sent)
		}
	})

	t.Run("finds the issue that carries the marker", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(listing(
				lookupItem(30, "unrelated", ""),
				lookupItem(31, "text\n\n<!-- kubelab-write:42 -->", ""),
			)))
		})
		got, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42))
		if err != nil || !got.Found || got.Number != 31 || got.URL != "https://forge.example/o/r/issues/31" {
			t.Fatalf("got %+v, err=%v", got, err)
		}
	})

	t.Run("the marker of outbox 12 is not the marker of outbox 123", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(listing(lookupItem(31, "<!-- kubelab-write:123 -->", ""))))
		})
		got, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(12))
		if err != nil || got.Found {
			t.Fatalf("a longer id matched a shorter one: %+v, err=%v", got, err)
		}
	})

	t.Run("a marker that is only part of the text does not match", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(listing(lookupItem(31, "kubelab-write:42", ""))))
		})
		if got, _ := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42)); got.Found {
			t.Fatalf("matched without the comment markers: %+v", got)
		}
	})

	t.Run("two issues with the marker resolve to the first one opened", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(listing(
				lookupItem(40, "<!-- kubelab-write:42 -->", ""),
				lookupItem(35, "<!-- kubelab-write:42 -->", ""),
			)))
		})
		got, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42))
		if err != nil || got.Number != 35 {
			t.Fatalf("got %+v, err=%v", got, err)
		}
	})

	if c.Pull != "" {
		t.Run("a pull request carrying the text is not the issue", func(t *testing.T) {
			srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte(listing(lookupItem(31, "<!-- kubelab-write:42 -->", c.Pull))))
			})
			if got, _ := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42)); got.Found {
				t.Fatalf("matched a pull request: %+v", got)
			}
		})
	}

	t.Run("reads the next page too", func(t *testing.T) {
		var srv *httptest.Server
		srv = serve(t, func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Query().Get("page") == "2" {
				_, _ = w.Write([]byte(listing(lookupItem(50, "<!-- kubelab-write:42 -->", ""))))
				return
			}
			w.Header().Set("Link", `<`+srv.URL+r.URL.Path+`?page=2>; rel="next"`)
			_, _ = w.Write([]byte(listing(lookupItem(51, "other", ""))))
		})
		got, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42))
		if err != nil || got.Number != 50 {
			t.Fatalf("got %+v, err=%v", got, err)
		}
	})

	t.Run("a listing that does not end is an error, never not-found", func(t *testing.T) {
		var srv *httptest.Server
		srv = serve(t, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Link", `<`+srv.URL+r.URL.Path+`>; rel="next"`)
			_, _ = w.Write([]byte(listing()))
		})
		got, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42))
		if err == nil || got.Found {
			t.Fatalf("got %+v, err=%v", got, err)
		}
		var ns *forge.NotSettledError
		if errors.As(err, &ns) {
			t.Fatal("an unreadable listing is not a wait")
		}
	})

	t.Run("a page that cannot be read is an error, never not-found", func(t *testing.T) {
		var srv *httptest.Server
		srv = serve(t, func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Query().Get("page") == "2" {
				http.Error(w, "boom", http.StatusInternalServerError)
				return
			}
			w.Header().Set("Link", `<`+srv.URL+r.URL.Path+`?page=2>; rel="next"`)
			_, _ = w.Write([]byte(listing()))
		})
		if _, err := c.New(srv.URL, afterSettle).FindCreated(context.Background(), q(42)); err == nil {
			t.Fatal("a failed second page read as an empty listing")
		}
	})

	t.Run("a forge that cannot be reached is an error", func(t *testing.T) {
		srv := httptest.NewServer(http.NotFoundHandler())
		url := srv.URL
		srv.Close()
		if _, err := c.New(url, afterSettle).FindCreated(context.Background(), q(42)); err == nil {
			t.Fatal("no error")
		}
	})

	t.Run("not found before the settle interval is a wait, not an answer (W8)", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(listing())) })
		early := func() time.Time { return sent.Add(settle - time.Second) }
		_, err := c.New(srv.URL, early).FindCreated(context.Background(), q(42))
		var ns *forge.NotSettledError
		if !errors.As(err, &ns) || !ns.Until.Equal(sent.Add(settle)) {
			t.Fatalf("want a NotSettledError until %s, got %v", sent.Add(settle), err)
		}
	})

	t.Run("found is safe at any time, even before the interval", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(listing(lookupItem(31, "<!-- kubelab-write:42 -->", ""))))
		})
		early := func() time.Time { return sent }
		got, err := c.New(srv.URL, early).FindCreated(context.Background(), q(42))
		if err != nil || !got.Found {
			t.Fatalf("got %+v, err=%v", got, err)
		}
	})

	t.Run("not found once the interval has passed is the answer that lets the worker post again", func(t *testing.T) {
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(listing())) })
		exactly := func() time.Time { return sent.Add(settle) }
		got, err := c.New(srv.URL, exactly).FindCreated(context.Background(), q(42))
		if err != nil || got.Found {
			t.Fatalf("got %+v, err=%v", got, err)
		}
	})

	t.Run("a lookup that names nothing to look for is refused before any call", func(t *testing.T) {
		var hits int
		srv := serve(t, func(w http.ResponseWriter, r *http.Request) { hits++ })
		w := c.New(srv.URL, afterSettle)
		for _, bad := range []forge.Lookup{
			{Source: c.Src, SentAt: sent, Settle: settle},
			{Source: c.Src, OutboxID: 42, Settle: settle},
			{Source: forge.Source{Forge: c.Src.Forge, Owner: "o", Repo: forge.EveryRepo}, OutboxID: 42, SentAt: sent, Settle: settle},
		} {
			if _, err := w.FindCreated(context.Background(), bad); err == nil {
				t.Errorf("%+v was accepted", bad)
			}
		}
		if hits != 0 {
			t.Errorf("the forge was called %d time(s)", hits)
		}
	})
}

func TestGitHubWriterFindsACreatedIssue(t *testing.T) {
	runLookupContract(t, lookupContract{
		Name: "github",
		Src:  ghSrc,
		New: func(baseURL string, now func() time.Time) forge.Writer {
			return &forge.GitHubWriter{BaseURL: baseURL, Token: "t", Now: now}
		},
		Path:  "/repos/o/r/issues",
		Query: url.Values{"state": {"all"}, "per_page": {"100"}},
		Pull:  `,"pull_request":{}`,
	})
}

func TestGiteaWriterFindsACreatedIssue(t *testing.T) {
	runLookupContract(t, lookupContract{
		Name: "gitea",
		Src:  gtSrc,
		New: func(baseURL string, now func() time.Time) forge.Writer {
			return &forge.GiteaWriter{BaseURL: baseURL, Token: "w", Now: now}
		},
		Path:  "/api/v1/repos/o/r/issues",
		Query: url.Values{"state": {"all"}, "type": {"issues"}, "limit": {"50"}},
	})
}

// The lookup is authenticated like the write: a Gitea listing of a private repository
// answers 404 without the token, and that must not read as "not found".
func TestLookupSendsTheWriterCredential(t *testing.T) {
	var gh, gt string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/v1/") {
			gt = r.Header.Get("Authorization")
		} else {
			gh = r.Header.Get("Authorization")
		}
		_, _ = w.Write([]byte("[]"))
	}))
	defer srv.Close()
	now := func() time.Time { return time.Date(2026, 11, 17, 13, 0, 0, 0, time.UTC) }
	sent := time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)

	_, _ = (&forge.GitHubWriter{BaseURL: srv.URL, Token: "t", Now: now}).FindCreated(context.Background(),
		forge.Lookup{Source: ghSrc, OutboxID: 1, SentAt: sent, Settle: time.Minute})
	_, _ = (&forge.GiteaWriter{BaseURL: srv.URL, Token: "w", Now: now}).FindCreated(context.Background(),
		forge.Lookup{Source: gtSrc, OutboxID: 1, SentAt: sent, Settle: time.Minute})
	if gh != "Bearer t" || gt != "token w" {
		t.Fatalf("github %q, gitea %q", gh, gt)
	}
}
