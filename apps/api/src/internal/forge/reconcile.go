package forge

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

// ReconcilePeriod and the alert bound of 20 minutes are one decision (tasks.md):
// as_of only moves on a successful read.
const ReconcilePeriod = 10 * time.Minute

// HourlyCallCeiling is the spec's ceiling on calls to one forge (AC4, #1501).
const HourlyCallCeiling = 1000

// ReadModel is what the reconcile needs from the store.
type ReadModel interface {
	// LastRead is the zero time for a source never read.
	LastRead(ctx context.Context, src Source) (time.Time, error)
	// SaveRead stores the items and moves as_of, in one transaction.
	SaveRead(ctx context.Context, src Source, items []Item, asOf time.Time) error
	// MarkUnreachable leaves as_of alone, so the source keeps its last known time.
	MarkUnreachable(ctx context.Context, src Source, at time.Time) error
}

// Reconciler re-reads each source, so a webhook that never arrived costs a
// delay and not a lost item.
type Reconciler struct {
	Readers map[string]Reader
	Sources []Source
	Model   ReadModel
	Now     func() time.Time // nil means time.Now
}

// Once reads every source. One failing source neither stops the others nor
// fails the cycle: the failure is recorded on that source. It reports whether
// every source was read.
func (r *Reconciler) Once(ctx context.Context) bool {
	ok := true
	for _, src := range r.Sources {
		if err := r.readSource(ctx, src); err != nil {
			ok = false
			log.Printf("forge reconcile: %s: %v", src, err)
			if mark := r.Model.MarkUnreachable(ctx, src, r.now()); mark != nil {
				log.Printf("forge reconcile: %s: record unreachable: %v", src, mark)
			}
		}
	}
	return ok
}

func (r *Reconciler) readSource(ctx context.Context, src Source) error {
	reader, ok := r.Readers[src.Forge]
	if !ok {
		return errors.New("no reader for this forge")
	}
	since, err := r.Model.LastRead(ctx, src)
	if err != nil {
		return err
	}
	// Taken before the read: an item changed during it is read again next cycle.
	started := r.now()
	items, err := reader.ListItems(ctx, src, since)
	if err != nil {
		return err
	}
	return r.Model.SaveRead(ctx, src, items, started)
}

// RetryPeriod is how soon a failed cycle runs again. A new pod's first read
// fails with the database refusing it, seen twice (staging and prod, 2026-11-02
// and 11-03), and waiting a full period for the next one left the source unread.
const RetryPeriod = time.Minute

// Run reconciles once at start and then every period, until ctx ends. A cycle
// with a failed source runs again after retry, if that is sooner.
func (r *Reconciler) Run(ctx context.Context, period, retry time.Duration) {
	for {
		wait := period
		if !r.Once(ctx) && retry < period {
			wait = retry
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}

func (r *Reconciler) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

// ParseSources reads `forge:owner/repo,forge:owner/repo`.
func ParseSources(spec string) ([]Source, error) {
	var sources []Source
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		name, path, ok := strings.Cut(part, ":")
		owner, repo, slash := strings.Cut(path, "/")
		if !ok || !slash || name == "" || owner == "" || repo == "" {
			return nil, fmt.Errorf("source %q is not forge:owner/repo", part)
		}
		sources = append(sources, Source{Forge: name, Owner: owner, Repo: repo})
	}
	return sources, nil
}

// ErrCeiling means the hour's calls are spent. It surfaces as an unreachable
// source, which is honest: the view is stale, not empty.
var ErrCeiling = errors.New("hourly call ceiling reached")

// Ceiling is a RoundTripper that refuses calls past Limit in a fixed hour window.
type Ceiling struct {
	Limit int
	Next  http.RoundTripper // nil means http.DefaultTransport
	Now   func() time.Time  // nil means time.Now

	mu     sync.Mutex
	window time.Time
	calls  int
}

// RoundTrip counts the call, then sends it or refuses it.
func (c *Ceiling) RoundTrip(req *http.Request) (*http.Response, error) {
	if !c.take() {
		return nil, ErrCeiling
	}
	next := c.Next
	if next == nil {
		next = http.DefaultTransport
	}
	return next.RoundTrip(req)
}

func (c *Ceiling) take() bool {
	now := time.Now
	if c.Now != nil {
		now = c.Now
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	hour := now().Truncate(time.Hour)
	if !hour.Equal(c.window) {
		c.window, c.calls = hour, 0
	}
	if c.calls >= c.Limit {
		return false
	}
	c.calls++
	return true
}
