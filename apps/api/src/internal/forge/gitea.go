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
	giteaPerPage  = 50
	giteaMaxPages = 200
	giteaAPIRoot  = "/api/v1/"
)

// Gitea reads a repository through the issues endpoint. Unlike GitHub's, it
// lists issues and pull requests apart (type=issues, type=pulls), so each
// repository takes two listings. BaseURL is the forge root (https://gitea.example);
// Token is optional, and an empty one sends no Authorization header.
type Gitea struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

// ListItems reads issues, then pull requests, changed since the given time.
// Either listing failing fails the whole read: half a repository is not a repository.
func (g *Gitea) ListItems(ctx context.Context, src Source, since time.Time) ([]Item, error) {
	var all []Item
	for _, kind := range []string{"issues", "pulls"} {
		q := url.Values{"state": {"all"}, "type": {kind}, "limit": {fmt.Sprint(giteaPerPage)}}
		if !since.IsZero() {
			q.Set("since", since.UTC().Format(time.RFC3339))
		}
		first := fmt.Sprintf("%s%srepos/%s/%s/issues?%s", strings.TrimSuffix(g.BaseURL, "/"), giteaAPIRoot, src.Owner, src.Repo, q.Encode())
		items, err := readPages(ctx, src, pagedRead{
			BaseURL:  g.BaseURL,
			First:    first,
			MaxPages: giteaMaxPages,
			HTTP:     g.HTTP,
			APIRoot:  giteaAPIRoot,
			Auth: func(req *http.Request) {
				if g.Token != "" {
					req.Header.Set("Authorization", "token "+g.Token)
				}
			},
		})
		if err != nil {
			return nil, err
		}
		all = append(all, items...)
	}
	return all, nil
}
