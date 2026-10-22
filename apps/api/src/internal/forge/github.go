package forge

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"time"
)

const githubPerPage = 100

// GitHub reads a repository through the issues endpoint, which lists pull
// requests too. BaseURL is the API root (https://api.github.com); Token is
// optional, and an empty one sends no Authorization header.
type GitHub struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

type githubItem struct {
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
	next := fmt.Sprintf("%s/repos/%s/%s/issues?%s", g.BaseURL, src.Owner, src.Repo, q.Encode())

	var items []Item
	for next != "" {
		page, link, err := g.page(ctx, next)
		if err != nil {
			return nil, &SourceError{Source: src, Err: err}
		}
		for _, raw := range page {
			items = append(items, raw.neutral(src))
		}
		next = link
	}
	return items, nil
}

func (g *GitHub) page(ctx context.Context, pageURL string) ([]githubItem, string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, pageURL, nil)
	if err != nil {
		return nil, "", err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	if g.Token != "" {
		req.Header.Set("Authorization", "Bearer "+g.Token)
	}
	client := g.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return nil, "", fmt.Errorf("github answered %s", resp.Status)
	}
	var page []githubItem
	if err := json.NewDecoder(resp.Body).Decode(&page); err != nil {
		return nil, "", fmt.Errorf("decode github page: %w", err)
	}
	link := ""
	if m := nextLink.FindStringSubmatch(resp.Header.Get("Link")); m != nil {
		link = m[1]
	}
	return page, link, nil
}

func (r githubItem) neutral(src Source) Item {
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
