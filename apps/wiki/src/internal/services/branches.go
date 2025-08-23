package services

// Fetch GitHub branches list with ETag (cheap polling).

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type Branch struct {
	Name string `json:"name"`
}

type BranchFetcher struct {
	Owner, Repo, Token string
	PerPage            int
	PollInterval       time.Duration
	client             *http.Client
	etag               string
}

func NewBranchFetcher(owner, repo, token string, poll time.Duration) *BranchFetcher {
	return &BranchFetcher{
		Owner:        owner,
		Repo:         repo,
		Token:        token,
		PerPage:      100,
		PollInterval: poll,
		client:       &http.Client{Timeout: 30 * time.Second},
	}
}

func (f *BranchFetcher) Start(ctx context.Context, onUpdate func(names []string)) error {
	if names, _ := f.fetchAll(ctx); len(names) > 0 {
		onUpdate(names)
	}
	t := time.NewTicker(f.PollInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			if names, _ := f.fetchAll(ctx); len(names) > 0 {
				onUpdate(names)
			}
		}
	}
}

func (f *BranchFetcher) fetchAll(ctx context.Context) ([]string, error) {
	page := 1
	var out []string
	etag := f.etag

	for {
		url := fmt.Sprintf("https://api.github.com/repos/%s/%s/branches?per_page=%d&page=%d",
			f.Owner, f.Repo, f.PerPage, page)
		req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
		if f.Token != "" {
			req.Header.Set("Authorization", "Bearer "+f.Token)
		}
		if etag != "" && page == 1 {
			req.Header.Set("If-None-Match", etag)
		}

		res, err := f.client.Do(req)
		if err != nil {
			return nil, err
		}
		if res.StatusCode == http.StatusNotModified && page == 1 {
			res.Body.Close()
			return nil, nil
		}
		if res.StatusCode != http.StatusOK {
			b, _ := io.ReadAll(res.Body)
			res.Body.Close()
			return nil, fmt.Errorf("branches %d: %s", res.StatusCode, string(b))
		}
		if page == 1 {
			f.etag = res.Header.Get("ETag")
		}

		var chunk []Branch
		if err := json.NewDecoder(res.Body).Decode(&chunk); err != nil {
			res.Body.Close()
			return nil, err
		}
		res.Body.Close()

		for _, b := range chunk {
			out = append(out, b.Name)
		}
		if len(chunk) < f.PerPage {
			break
		}
		page++
	}
	return out, nil
}

// helpers
func SplitCSV(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

func AtoiDefault(s string, def int) int {
	if n, err := strconv.Atoi(strings.TrimSpace(s)); err == nil {
		return n
	}
	return def
}
