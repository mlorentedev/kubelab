package forge

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// giteaLookupPages bounds the marker search: 40 pages of 50 is 2,000 issues changed since a
// create was sent. Past that the search is an error, not a "not found".
const giteaLookupPages = 40

// GiteaWriter writes to Gitea's issue endpoints with the issue_writer token (FORGE_GITEA_WRITE_TOKEN,
// prod only). BaseURL is the forge root. Unlike the reader, an empty Token does not mean "send
// without Authorization": the writer is then not configured and sends nothing. Now is the clock
// of the marker search's settle interval; nil means time.Now.
type GiteaWriter struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
	Now     func() time.Time
}

func (g *GiteaWriter) engine() *issueWriter {
	return &issueWriter{
		http: g.HTTP,
		root: strings.TrimSuffix(g.BaseURL, "/") + strings.TrimSuffix(giteaAPIRoot, "/"),
		authorize: func(context.Context) (func(*http.Request), error) {
			if g.Token == "" {
				return nil, fmt.Errorf("%w: gitea has no write token", ErrNoWriter)
			}
			return func(req *http.Request) {
				req.Header.Set("Accept", "application/json")
				req.Header.Set("Authorization", "token "+g.Token)
			}, nil
		},
		removeLabel: removeGiteaLabel,
		listing: func(e *issueWriter, src Source, since time.Time) string {
			// type=issues keeps pull requests out of the listing, as the reader's does.
			q := url.Values{
				"state": {"all"}, "type": {"issues"}, "limit": {fmt.Sprint(giteaPerPage)},
				"since": {since.UTC().Format(time.RFC3339)},
			}
			return e.issues(src) + "?" + q.Encode()
		},
		apiRoot:  giteaAPIRoot,
		maxPages: giteaLookupPages,
		now:      clock(g.Now),
	}
}

// Write makes one request and classifies the answer.
func (g *GiteaWriter) Write(ctx context.Context, w Write) Result { return g.engine().Write(ctx, w) }

// FindCreated finds the issue a create made, by its marker.
func (g *GiteaWriter) FindCreated(ctx context.Context, lk Lookup) (LookupResult, error) {
	return g.engine().FindCreated(ctx, lk)
}

// removeGiteaLabel deletes by the label's numeric id, the only form DELETE takes (v1.27.3,
// DeleteIssueLabel), so the issue's own labels are read to find it. A label the issue does not
// carry is already removed, which is what a retry after a lost answer finds.
func removeGiteaLabel(ctx context.Context, e *issueWriter, auth func(*http.Request), w Write) Result {
	labels, r := e.issueLabels(ctx, auth, e.issue(w)+"/labels")
	if !r.ok() {
		return r.failure(false)
	}
	for _, l := range labels {
		if strings.EqualFold(l.Name, w.Label) {
			return e.send(ctx, auth, http.MethodDelete, fmt.Sprintf("%s/labels/%d", e.issue(w), l.ID), nil, false)
		}
	}
	return applied(r.Status)
}

func clock(now func() time.Time) func() time.Time {
	if now != nil {
		return now
	}
	return time.Now
}
