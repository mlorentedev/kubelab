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
