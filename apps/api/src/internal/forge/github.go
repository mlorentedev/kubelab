package forge

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"time"
)

const (
	githubPerPage = 100
	// githubMaxPages bounds a listing so a server that always answers with a next
	// link cannot keep the reader looping: 100 pages of 100 is 10,000 items.
	githubMaxPages = 100
)

// GitHub reads a repository through the issues endpoint, which lists pull
// requests too. BaseURL is the API root (https://api.github.com); Token is
// optional, and an empty one sends no Authorization header.
type GitHub struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

type restItem struct {
	Number    int       `json:"number"`
	Title     string    `json:"title"`
	State     string    `json:"state"`
	HTMLURL   string    `json:"html_url"`
	UpdatedAt time.Time `json:"updated_at"`
	User      struct {
		Login string `json:"login"`
	} `json:"user"`
	Assignees []struct {
		Login string `json:"login"`
	} `json:"assignees"`
	Labels []struct {
		Name string `json:"name"`
	} `json:"labels"`
	PullRequest *struct{} `json:"pull_request"`
}

var nextLink = regexp.MustCompile(`<([^>]+)>;\s*rel="next"`)

// ListItems pages through every item changed since the given time.
func (g *GitHub) ListItems(ctx context.Context, src Source, since time.Time) ([]Item, error) {
	q := url.Values{"state": {"all"}, "per_page": {fmt.Sprint(githubPerPage)}}
	if !since.IsZero() {
		q.Set("since", since.UTC().Format(time.RFC3339))
	}
	first := fmt.Sprintf("%s/repos/%s/%s/issues?%s", g.BaseURL, src.Owner, src.Repo, q.Encode())
	return readPages(ctx, src, pagedRead{
		BaseURL:  g.BaseURL,
		First:    first,
		MaxPages: githubMaxPages,
		HTTP:     g.HTTP,
		Auth: func(req *http.Request) {
			req.Header.Set("Accept", "application/vnd.github+json")
			if g.Token != "" {
				req.Header.Set("Authorization", "Bearer "+g.Token)
			}
		},
	})
}

func (r restItem) neutral(src Source) Item {
	it := Item{
		Source:    src,
		Number:    r.Number,
		Kind:      KindIssue,
		Title:     r.Title,
		State:     r.State,
		Author:    r.User.Login,
		URL:       r.HTMLURL,
		UpdatedAt: r.UpdatedAt,
	}
	if r.PullRequest != nil {
		it.Kind = KindPull
	}
	for _, a := range r.Assignees {
		it.Assignees = append(it.Assignees, a.Login)
	}
	for _, l := range r.Labels {
		it.Labels = append(it.Labels, l.Name)
	}
	return it
}

// sameOrigin reports whether link has the scheme and host of base. The token is
// attached to every request, so a next link naming another host must not be followed.
func sameOrigin(base *url.URL, link string) bool {
	u, err := url.Parse(link)
	return err == nil && u.Scheme == base.Scheme && u.Host == base.Host
}
