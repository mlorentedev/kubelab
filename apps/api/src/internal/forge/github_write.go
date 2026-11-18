package forge

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	githubAPIVersion = "2022-11-28"
	// githubLookupPages bounds the marker search: 20 pages of 100 is 2,000 issues changed since a
	// create was sent. Past that the search is an error, not a "not found".
	githubLookupPages = 20
)

// GitHubWriter writes to GitHub's issue endpoints with the App installation token, the same
// credential the reader uses (the App holds Issues: write since 2026-11-16). BaseURL is the API
// root. Tokens supplies a fresh token per write and wins over Token; with neither, the writer is
// not configured and sends nothing. Now is the clock of the marker search's settle interval;
// nil means time.Now.
type GitHubWriter struct {
	BaseURL string
	Token   string
	Tokens  func(context.Context) (string, error)
	HTTP    *http.Client
	Now     func() time.Time
}

func (g *GitHubWriter) engine() *issueWriter {
	return &issueWriter{
		http: g.HTTP,
		root: strings.TrimSuffix(g.BaseURL, "/"),
		site: strings.TrimSuffix(g.BaseURL, "/"),
		authorize: func(ctx context.Context) (func(*http.Request), error) {
			token := g.Token
			if g.Tokens != nil {
				var err error
				if token, err = g.Tokens(ctx); err != nil {
					return nil, fmt.Errorf("github installation token: %w", err)
				}
			}
			if token == "" {
				return nil, fmt.Errorf("%w: github has no credential", ErrNoWriter)
			}
			return func(req *http.Request) {
				req.Header.Set("Accept", "application/vnd.github+json")
				req.Header.Set("X-GitHub-Api-Version", githubAPIVersion)
				req.Header.Set("Authorization", "Bearer "+token)
			}, nil
		},
		removeLabel: removeGitHubLabel,
		listing: func(e *issueWriter, src Source, since time.Time) string {
			q := url.Values{
				"state": {"all"}, "sort": {"created"}, "direction": {"desc"},
				"per_page": {fmt.Sprint(githubPerPage)}, "since": {since.UTC().Format(time.RFC3339)},
			}
			return e.issues(src) + "?" + q.Encode()
		},
		maxPages: githubLookupPages,
		now:      clock(g.Now),
	}
}

// Write makes one request and classifies the answer.
func (g *GitHubWriter) Write(ctx context.Context, w Write) Result { return g.engine().Write(ctx, w) }

// FindCreated finds the issue a create made, by its marker.
func (g *GitHubWriter) FindCreated(ctx context.Context, lk Lookup) (LookupResult, error) {
	return g.engine().FindCreated(ctx, lk)
}

// removeGitHubLabel deletes the label by name. GitHub answers 404 when the label is not on the
// issue and when the issue is gone, so a 404 alone settles nothing: the issue's labels say which.
// Without that, a removal whose answer was lost would fail terminally on its retry.
func removeGitHubLabel(ctx context.Context, e *issueWriter, auth func(*http.Request), w Write) Result {
	r := call(ctx, e.http, auth, http.MethodDelete, e.issue(w)+"/labels/"+url.PathEscape(w.Label), nil)
	if r.ok() {
		return applied(r.Status)
	}
	if r.Err != nil || r.Status != http.StatusNotFound {
		return r.failure(false)
	}
	labels, probe := e.issueLabels(ctx, auth, e.issue(w)+"/labels?per_page="+fmt.Sprint(githubPerPage))
	switch {
	case !probe.ok():
		return probe.failure(false)
	case hasLabel(labels, w.Label):
		// The delete said it was not there and the issue says it is: do not guess, try again.
		return Result{Outcome: OutcomeRetry, Status: r.Status, Err: fmt.Errorf("forge answered 404 to a label the issue carries")}
	}
	return applied(probe.Status)
}
