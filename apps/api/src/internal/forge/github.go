package forge

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"strings"
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
// optional, and an empty one sends no Authorization header. Tokens, when set,
// supplies a fresh token per read and wins over Token (AppTokens.Token).
type GitHub struct {
	BaseURL string
	Token   string
	Tokens  func(context.Context) (string, error)
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

// token is the credential for one read: a fresh App token when Tokens is set.
func (g *GitHub) token(ctx context.Context) (string, error) {
	if g.Tokens != nil {
		return g.Tokens(ctx)
	}
	return g.Token, nil
}

func (g *GitHub) read(token, first string) pagedRead {
	return pagedRead{
		BaseURL:  g.BaseURL,
		First:    first,
		MaxPages: githubMaxPages,
		HTTP:     g.HTTP,
		Auth: func(req *http.Request) {
			req.Header.Set("Accept", "application/vnd.github+json")
			if token != "" {
				req.Header.Set("Authorization", "Bearer "+token)
			}
		},
	}
}

// ListItems pages through every item changed since the given time.
func (g *GitHub) ListItems(ctx context.Context, src Source, since time.Time) ([]Item, error) {
	token, err := g.token(ctx)
	if err != nil {
		return nil, &SourceError{Source: src, Err: err}
	}
	q := url.Values{"state": {"all"}, "per_page": {fmt.Sprint(githubPerPage)}}
	if !since.IsZero() {
		q.Set("since", since.UTC().Format(time.RFC3339))
	}
	first := fmt.Sprintf("%s/repos/%s/%s/issues?%s", g.BaseURL, src.Owner, src.Repo, q.Encode())
	return readPages(ctx, src, g.read(token, first))
}

// ListRepos lists the owner's repositories the App installation can read, without
// forks or archived ones. The installation spans every owner it was granted, so the
// owner is filtered here. A page that fails fails the listing.
func (g *GitHub) ListRepos(ctx context.Context, owner string) ([]Source, error) {
	token, err := g.token(ctx)
	if err != nil {
		return nil, err
	}
	p := g.read(token, fmt.Sprintf("%s/installation/repositories?per_page=%d", g.BaseURL, githubPerPage))
	base, err := url.Parse(g.BaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse base url: %w", err)
	}
	var repos []Source
	next := p.First
	for pages := 0; next != ""; pages++ {
		if pages == p.MaxPages {
			return nil, fmt.Errorf("more than %d pages", p.MaxPages)
		}
		var page struct {
			Repositories []struct {
				Name     string `json:"name"`
				Fork     bool   `json:"fork"`
				Archived bool   `json:"archived"`
				Owner    struct {
					Login string `json:"login"`
				} `json:"owner"`
			} `json:"repositories"`
		}
		link, err := getPage(ctx, p, next, &page)
		if err != nil {
			return nil, err
		}
		if link != "" && !sameOrigin(base, link) {
			return nil, fmt.Errorf("next page points off %s", base.Host)
		}
		for _, r := range page.Repositories {
			if strings.EqualFold(r.Owner.Login, owner) && !r.Fork && !r.Archived {
				repos = append(repos, Source{Forge: "github", Owner: r.Owner.Login, Repo: r.Name})
			}
		}
		next = link
	}
	return repos, nil
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
