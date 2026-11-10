// Package forge reads issues and pull requests from the forges the operator
// works on, behind one interface so the read model never sees a vendor shape.
// CONSOLE-004 (ADR-066 amendment): reads only; writes are a separate slice.
package forge

import (
	"context"
	"fmt"
	"time"
)

// Kind tells an issue from a pull request.
type Kind string

const (
	KindIssue Kind = "issue"
	KindPull  Kind = "pull"
)

// Source names one repository on one forge.
type Source struct {
	Forge string // "github" or "gitea"
	Owner string
	Repo  string
}

func (s Source) String() string { return fmt.Sprintf("%s:%s/%s", s.Forge, s.Owner, s.Repo) }

// EveryRepo as a source's Repo stands for every repository the owner has on that
// forge, so a repository created later is read without a new declaration.
const EveryRepo = "*"

// Wildcard reports whether the source stands for an owner's every repository.
func (s Source) Wildcard() bool { return s.Repo == EveryRepo }

// Item is the forge-neutral shape of an issue or a pull request.
type Item struct {
	Source    Source
	Number    int
	Kind      Kind
	Title     string
	State     string // "open" or "closed"
	Author    string
	Assignees []string
	Labels    []string
	URL       string
	UpdatedAt time.Time
}

// SourceState is what the queue shows about a source: when it was last read in
// full and whether the last attempt reached it. A source never read has no time.
type SourceState struct {
	Source    Source
	AsOf      *time.Time
	Reachable bool
}

// QueueKey is an item's place in the queue: newest first, ties broken by the
// item's identity, so a page boundary never skips or repeats an item.
type QueueKey struct {
	UpdatedAt time.Time
	Source    Source
	Number    int
}

// Key is the item's place in the queue.
func (it Item) Key() QueueKey {
	return QueueKey{UpdatedAt: it.UpdatedAt, Source: it.Source, Number: it.Number}
}

// QueuePage is one page of the queue: every declared source's state, the open
// items after a key, and how many open items the declared sources hold in all.
type QueuePage struct {
	States []SourceState
	Items  []Item
	Total  int
}

// Reader lists the items of one source changed since a point in time. A zero
// since lists everything.
type Reader interface {
	ListItems(ctx context.Context, src Source, since time.Time) ([]Item, error)
}

// SourceError means a source could not be read. It carries the source so the
// caller can mark that source unreachable with its last read time instead of
// rendering an empty queue.
type SourceError struct {
	Source Source
	Err    error
}

func (e *SourceError) Error() string { return fmt.Sprintf("read %s: %v", e.Source, e.Err) }
func (e *SourceError) Unwrap() error { return e.Err }
