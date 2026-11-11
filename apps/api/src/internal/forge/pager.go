package forge

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
)

// pagedRead describes one paged listing: where it starts, how the request is
// authenticated and how many pages it may take.
type pagedRead struct {
	BaseURL  string
	First    string
	MaxPages int
	HTTP     *http.Client
	Auth     func(*http.Request)
	// Rehost follows a next link on any host by reading its path and query at
	// BaseURL. Gitea needs it: its links name ROOT_URL, not the address read.
	Rehost bool
}

// readPages follows the Link rel="next" header until the listing ends. Every
// failure is a SourceError, so an unreachable forge never reads as an empty one.
func readPages(ctx context.Context, src Source, p pagedRead) ([]Item, error) {
	base, err := url.Parse(p.BaseURL)
	if err != nil {
		return nil, &SourceError{Source: src, Err: fmt.Errorf("parse base url: %w", err)}
	}
	var items []Item
	next := p.First
	for pages := 0; next != ""; pages++ {
		if pages == p.MaxPages {
			return nil, &SourceError{Source: src, Err: fmt.Errorf("more than %d pages", p.MaxPages)}
		}
		page, link, err := fetchPage(ctx, p, next)
		if err != nil {
			return nil, &SourceError{Source: src, Err: err}
		}
		if link, err = nextOnBase(base, link, p.Rehost); err != nil {
			return nil, &SourceError{Source: src, Err: err}
		}
		for _, raw := range page {
			items = append(items, raw.neutral(src))
		}
		next = link
	}
	return items, nil
}

func fetchPage(ctx context.Context, p pagedRead, pageURL string) ([]restItem, string, error) {
	var page []restItem
	link, err := getPage(ctx, p, pageURL, &page)
	return page, link, err
}

// getPage fetches one page into out and returns the next page's URL, if any.
func getPage(ctx context.Context, p pagedRead, pageURL string, out any) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, pageURL, nil)
	if err != nil {
		return "", err
	}
	p.Auth(req)
	client := p.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return "", fmt.Errorf("forge answered %s", resp.Status)
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return "", fmt.Errorf("decode page: %w", err)
	}
	link := ""
	if m := nextLink.FindStringSubmatch(resp.Header.Get("Link")); m != nil {
		link = m[1]
	}
	return link, nil
}

// nextOnBase returns the next page's URL on base. With rehost, the link's path
// and query are read at base, so the token only ever reaches the configured
// host; without it, a link naming another host is refused.
func nextOnBase(base *url.URL, link string, rehost bool) (string, error) {
	if link == "" {
		return "", nil
	}
	if !rehost {
		if !sameOrigin(base, link) {
			return "", fmt.Errorf("next page points off %s", base.Host)
		}
		return link, nil
	}
	u, err := url.Parse(link)
	if err != nil {
		return "", fmt.Errorf("parse next link: %w", err)
	}
	return (&url.URL{Scheme: base.Scheme, Host: base.Host, Path: u.Path, RawQuery: u.RawQuery}).String(), nil
}
