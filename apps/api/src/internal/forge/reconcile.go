package forge

import (
	"context"
	"errors"
	"fmt"
	"log"
	"log/slog"
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
	Catalog *Catalog // what to read; each cycle lists its wildcards first
	Model   ReadModel
	Now     func() time.Time // nil means time.Now
	// Known returns the sources already stored. A cycle that leaves a wildcard with
	// neither a listing nor a seed asks it again, so a seed the start could not take
	// is retried (#3247). Nil never asks.
	Known  func(context.Context) ([]Source, error)
	Events *slog.Logger // nil writes JSON lines to stderr (events.go)
}

// Once lists the catalog's wildcards and reads every source. Neither a failed
// listing nor a failing source stops the cycle: the listing keeps its last set
// and the failure is recorded on that source. It returns the sources it could
// not read.
func (r *Reconciler) Once(ctx context.Context) []Source {
	if err := r.Catalog.Resolve(ctx); err != nil {
		log.Printf("forge reconcile: listing: %v", err)
	}
	r.seed(ctx)
	return r.read(ctx, r.Catalog.Current(), "full")
}

// seed asks the store for what it already read while a wildcard is unresolved.
func (r *Reconciler) seed(ctx context.Context) {
	if r.Known == nil || len(r.Catalog.Unresolved()) == 0 {
		return
	}
	known, err := r.Known(ctx)
	if err != nil {
		log.Printf("forge reconcile: seed from the store: %v", err)
		return
	}
	r.Catalog.Seed(known)
}

func (r *Reconciler) read(ctx context.Context, sources []Source, scope string) []Source {
	began := time.Now()
	var failed []Source
	for _, src := range sources {
		since, err := r.readSource(ctx, src)
		if err != nil {
			failed = append(failed, src)
			if mark := r.Model.MarkUnreachable(ctx, src, r.now()); mark != nil {
				log.Printf("forge reconcile: %s: record unreachable: %v", src, mark)
			}
		}
		r.freshness(src, since, err)
	}
	emit(r.Events, slog.LevelInfo, EventReconcileCycle, slog.String("scope", scope),
		slog.Int("sources", len(sources)), slog.Int("failed", len(failed)),
		slog.Int64("duration_ms", time.Since(began).Milliseconds()))
	return failed
}

// freshness reports a source's as_of after a read attempt. A failed read leaves
// as_of where it was, so its age keeps growing; a source never read has neither.
func (r *Reconciler) freshness(src Source, asOf time.Time, err error) {
	attrs := []slog.Attr{slog.String("source", src.String()), slog.Bool("reachable", err == nil)}
	if !asOf.IsZero() {
		attrs = append(attrs, slog.String("as_of", asOf.UTC().Format(time.RFC3339)),
			slog.Float64("age_seconds", r.now().Sub(asOf).Seconds()))
	}
	level := slog.LevelInfo
	if err != nil {
		level = slog.LevelWarn
		attrs = append(attrs, slog.String("error", err.Error()))
	}
	emit(r.Events, level, EventSourceFreshness, attrs...)
}

// readSource returns the source's as_of after the attempt: the read's start when it
// was saved, the last one otherwise, and zero when there is none or it is unknown.
func (r *Reconciler) readSource(ctx context.Context, src Source) (time.Time, error) {
	reader, ok := r.Readers[src.Forge]
	if !ok {
		return time.Time{}, errors.New("no reader for this forge")
	}
	since, err := r.Model.LastRead(ctx, src)
	if err != nil {
		return time.Time{}, err
	}
	// Taken before the read: an item changed during it is read again next cycle.
	started := r.now()
	items, err := reader.ListItems(ctx, src, since)
	if err != nil {
		return since, err
	}
	if err := r.Model.SaveRead(ctx, src, items, started); err != nil {
		return since, err
	}
	return started, nil
}

// RetryPeriod is how soon a failed cycle runs again. A new pod's first read
// fails with the database refusing it, seen twice (staging and prod, 2026-11-02
// and 11-03), and waiting a full period for the next one left the source unread.
const RetryPeriod = time.Minute

// Run reconciles every source at start and then a period after each cycle, until ctx ends.
// A source that failed is read again after retry, alone, until the next full
// cycle: a forge that stays down must not multiply the calls to the others.
func (r *Reconciler) Run(ctx context.Context, period, retry time.Duration) {
	for {
		failed := r.Once(ctx)
		// Counted from the end of the cycle, so a cycle slower than the period
		// still leaves a full period before the next one.
		next := time.Now().Add(period)
		for len(failed) > 0 && retry < time.Until(next) {
			if !sleep(ctx, retry) {
				return
			}
			failed = r.read(ctx, failed, "retry")
		}
		if !sleep(ctx, time.Until(next)) {
			return
		}
	}
}

// sleep waits for d, and reports false if ctx ended first.
func sleep(ctx context.Context, d time.Duration) bool {
	select {
	case <-ctx.Done():
		return false
	case <-time.After(d):
		return true
	}
}

func (r *Reconciler) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

// ParseSources reads `forge:owner/repo,forge:owner/repo`; `forge:owner/*` names
// every repository of the owner (EveryRepo). The owner is never a wildcard.
func ParseSources(spec string) ([]Source, error) {
	var sources []Source
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		name, path, ok := strings.Cut(part, ":")
		owner, repo, slash := strings.Cut(path, "/")
		badWildcard := strings.Contains(owner, "*") || (strings.Contains(repo, "*") && repo != EveryRepo)
		if !ok || !slash || name == "" || owner == "" || repo == "" || badWildcard {
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
