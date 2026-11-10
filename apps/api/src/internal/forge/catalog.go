package forge

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
)

// Lister lists the repositories an owner has on one forge, leaving out forks and
// archived ones. A listing that cannot be completed is an error, never a partial set.
type Lister interface {
	ListRepos(ctx context.Context, owner string) ([]Source, error)
}

// Catalog turns the declaration into the sources to read. A named source is read
// as declared; an owner's wildcard becomes the repositories its forge lists, so a
// repository created later is read from the next Resolve on, with no new
// declaration. Each wildcard keeps its last good listing: a forge that cannot be
// listed leaves the set as it was (AC1), and only a listing that succeeds retires
// a repository.
type Catalog struct {
	Declared []Source
	Listers  map[string]Lister

	mu     sync.RWMutex
	listed map[Source][]Source // wildcard -> its last good listing
}

// Resolve lists every wildcard once. It returns the wildcards it could not list,
// joined; their previous listing stays in Current.
func (c *Catalog) Resolve(ctx context.Context) error {
	var errs []error
	fresh := map[Source][]Source{}
	for _, pattern := range c.Declared {
		if !pattern.Wildcard() {
			continue
		}
		repos, err := c.list(ctx, pattern)
		if err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", pattern, err))
			continue
		}
		fresh[pattern] = repos
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.listed == nil {
		c.listed = map[Source][]Source{}
	}
	for pattern, repos := range fresh {
		c.listed[pattern] = repos
	}
	return errors.Join(errs...)
}

// Seed gives each wildcard not yet listed the sources the store already reads,
// so a pod that starts while its forge cannot be listed still serves them. A
// listing, once there is one, wins: Seed never replaces it.
func (c *Catalog) Seed(known []Source) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.listed == nil {
		c.listed = map[Source][]Source{}
	}
	for _, pattern := range c.Declared {
		if _, done := c.listed[pattern]; done || !pattern.Wildcard() {
			continue
		}
		c.listed[pattern] = owned(pattern, known)
	}
}

func (c *Catalog) list(ctx context.Context, pattern Source) ([]Source, error) {
	lister, ok := c.Listers[pattern.Forge]
	if !ok {
		return nil, errors.New("no lister for this forge")
	}
	repos, err := lister.ListRepos(ctx, pattern.Owner)
	if err != nil {
		return nil, err
	}
	return owned(pattern, repos), nil
}

// owned keeps the sources a wildcard names: its forge and its owner. A lister or
// a store answering beyond them widens nothing.
func owned(pattern Source, sources []Source) []Source {
	own := []Source{}
	for _, r := range sources {
		if r.Forge == pattern.Forge && strings.EqualFold(r.Owner, pattern.Owner) && r.Repo != "" && !r.Wildcard() {
			own = append(own, r)
		}
	}
	return own
}

// Current is the set to read now: the named sources and every wildcard's last
// good listing, each once, sorted.
func (c *Catalog) Current() []Source {
	c.mu.RLock()
	defer c.mu.RUnlock()
	// Keyed without case, as the forges compare names.
	seen := map[string]Source{}
	add := func(s Source) { seen[strings.ToLower(s.String())] = s }
	for _, s := range c.Declared {
		if s.Wildcard() {
			for _, r := range c.listed[s] {
				add(r)
			}
		} else {
			add(s)
		}
	}
	out := make([]Source, 0, len(seen))
	for _, s := range seen {
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].String() < out[j].String() })
	return out
}
