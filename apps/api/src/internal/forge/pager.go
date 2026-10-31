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
		if link != "" && !sameOrigin(base, link) {
			return nil, &SourceError{Source: src, Err: fmt.Errorf("next page points off %s", base.Host)}
		}
		for _, raw := range page {
			items = append(items, raw.neutral(src))
		}
		next = link
	}
	return items, nil
}

func fetchPage(ctx context.Context, p pagedRead, pageURL string) ([]restItem, string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, pageURL, nil)
	if err != nil {
		return nil, "", err
	}
	p.Auth(req)
	client := p.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return nil, "", fmt.Errorf("forge answered %s", resp.Status)
	}
	var page []restItem
	if err := json.NewDecoder(resp.Body).Decode(&page); err != nil {
		return nil, "", fmt.Errorf("decode page: %w", err)
	}
	link := ""
	if m := nextLink.FindStringSubmatch(resp.Header.Get("Link")); m != nil {
		link = m[1]
	}
	return page, link, nil
}
