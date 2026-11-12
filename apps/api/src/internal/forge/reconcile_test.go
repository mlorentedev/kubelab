package forge_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

type fakeModel struct {
	lastRead    map[string]time.Time
	saved       map[string][]forge.Item
	unreachable []string
}

func newModel() *fakeModel {
	return &fakeModel{lastRead: map[string]time.Time{}, saved: map[string][]forge.Item{}}
}

func (m *fakeModel) LastRead(_ context.Context, s forge.Source) (time.Time, error) {
	return m.lastRead[s.String()], nil
}

func (m *fakeModel) SaveRead(_ context.Context, s forge.Source, items []forge.Item, at time.Time) error {
	m.saved[s.String()], m.lastRead[s.String()] = items, at
	return nil
}

func (m *fakeModel) MarkUnreachable(_ context.Context, s forge.Source, _ time.Time) error {
	m.unreachable = append(m.unreachable, s.String())
	return nil
}

type fakeReader struct {
	items []forge.Item
	err   error
	since time.Time
}

func (f *fakeReader) ListItems(_ context.Context, s forge.Source, since time.Time) ([]forge.Item, error) {
	f.since = since
	if f.err != nil {
		return nil, &forge.SourceError{Source: s, Err: f.err}
	}
	return f.items, nil
}

func TestReconcileOneDownSourceLeavesTheOtherRead(t *testing.T) {
	up := forge.Source{Forge: "github", Owner: "o", Repo: "up"}
	down := forge.Source{Forge: "gitea", Owner: "o", Repo: "down"}
	model := newModel()
	last := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	model.lastRead[down.String()] = last
	now := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	reader := &fakeReader{items: []forge.Item{{Number: 1}}}

	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": reader, "gitea": &fakeReader{err: errors.New("down")}},
		Catalog: &forge.Catalog{Declared: []forge.Source{down, up}},
		Model:   model,
		Now:     func() time.Time { return now },
	}
	r.Once(context.Background())

	if len(model.saved[up.String()]) != 1 || !model.lastRead[up.String()].Equal(now) {
		t.Fatalf("up source not saved: %+v", model)
	}
	if len(model.unreachable) != 1 || model.unreachable[0] != down.String() {
		t.Fatalf("unreachable = %v", model.unreachable)
	}
	if !model.lastRead[down.String()].Equal(last) {
		t.Fatal("as_of moved on a failed read")
	}
	r.Once(context.Background())
	if !reader.since.Equal(now) {
		t.Fatalf("second read since = %v, want the first read's start", reader.since)
	}
}

func TestReconcileNoReaderIsUnreachable(t *testing.T) {
	src := forge.Source{Forge: "gitlab", Owner: "o", Repo: "r"}
	model := newModel()
	r := forge.Reconciler{Catalog: &forge.Catalog{Declared: []forge.Source{src}}, Model: model}
	r.Once(context.Background())
	if len(model.unreachable) != 1 {
		t.Fatalf("unreachable = %v", model.unreachable)
	}
}

func TestParseSources(t *testing.T) {
	got, err := forge.ParseSources(" github:o/r, gitea:a/b,")
	if err != nil || len(got) != 2 || got[1] != (forge.Source{Forge: "gitea", Owner: "a", Repo: "b"}) {
		t.Fatalf("got %v, %v", got, err)
	}
	// An owner's every repository is `forge:owner/*`; the owner itself is never a wildcard.
	all, err := forge.ParseSources("github:o/*")
	if err != nil || len(all) != 1 || !all[0].Wildcard() {
		t.Fatalf("github:o/*: got %v, %v", all, err)
	}
	for _, bad := range []string{"github", "github:o", ":o/r", "github:/r", "github:*/r", "github:*/*", "github:o/r*"} {
		if _, err := forge.ParseSources(bad); err == nil {
			t.Errorf("%q: want an error", bad)
		}
	}
}

// A reconcile cycle over a real paged read stays far under the ceiling at the
// declared period, and the ceiling cuts a read off instead of overspending.
func TestReconcileStaysUnderTheHourlyCeiling(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		fmt.Fprint(w, `[]`)
	}))
	defer srv.Close()

	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}
	model := newModel()
	now := time.Date(2026, 11, 2, 8, 0, 0, 0, time.UTC)
	ceiling := &forge.Ceiling{Limit: forge.HourlyCallCeiling, Now: func() time.Time { return now }}
	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": &forge.GitHub{BaseURL: srv.URL, HTTP: &http.Client{Transport: ceiling}}},
		Catalog: &forge.Catalog{Declared: []forge.Source{src}},
		Model:   model,
		Now:     func() time.Time { return now },
	}
	cycles := int(time.Hour / forge.ReconcilePeriod)
	for i := 0; i < cycles; i++ {
		r.Once(context.Background())
	}
	if calls != cycles || calls >= forge.HourlyCallCeiling {
		t.Fatalf("calls = %d over %d cycles", calls, cycles)
	}

	tight := &forge.Ceiling{Limit: 1, Now: func() time.Time { return now }}
	r.Readers["github"] = &forge.GitHub{BaseURL: srv.URL, HTTP: &http.Client{Transport: tight}}
	r.Once(context.Background())
	r.Once(context.Background())
	if len(model.unreachable) != 1 {
		t.Fatalf("past the ceiling the source must read as unreachable: %v", model.unreachable)
	}
}

// flakyReader fails its first call, as the database did for a new pod, and
// signals its first success.
type flakyReader struct {
	mu    sync.Mutex
	calls int
	read  chan struct{}
	once  sync.Once
}

func (f *flakyReader) ListItems(_ context.Context, s forge.Source, _ time.Time) ([]forge.Item, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	if f.calls == 1 {
		return nil, &forge.SourceError{Source: s, Err: errors.New("connection refused")}
	}
	f.once.Do(func() { close(f.read) })
	return nil, nil
}

// countingReader counts its calls, and fails each one when err is set.
type countingReader struct {
	mu    sync.Mutex
	calls int
	err   error
}

func (c *countingReader) ListItems(_ context.Context, s forge.Source, _ time.Time) ([]forge.Item, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.calls++
	if c.err != nil {
		return nil, &forge.SourceError{Source: s, Err: c.err}
	}
	return nil, nil
}

func (c *countingReader) count() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.calls
}

func TestADownSourceIsRetriedAloneUntilTheNextCycle(t *testing.T) {
	up := forge.Source{Forge: "github", Owner: "o", Repo: "up"}
	down := forge.Source{Forge: "gitea", Owner: "o", Repo: "down"}
	healthy := &countingReader{}
	broken := &countingReader{err: errors.New("down")}
	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": healthy, "gitea": broken},
		Catalog: &forge.Catalog{Declared: []forge.Source{up, down}},
		Model:   newModel(),
	}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	r.Run(ctx, time.Hour, 5*time.Millisecond)
	// About 40 retries fit in 200ms at 5ms each: fewer means no retry, far more means no pause.
	if n := broken.count(); n < 3 || n > 60 {
		t.Fatalf("the down source was read %d times in 200ms with a 5ms retry", n)
	}
	if n := healthy.count(); n != 1 {
		t.Fatalf("the healthy source was read %d times while the other was retried", n)
	}
}

func TestFailedCycleRetriesBeforeThePeriod(t *testing.T) {
	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}
	reader := &flakyReader{read: make(chan struct{})}
	r := forge.Reconciler{Readers: map[string]forge.Reader{"github": reader}, Catalog: &forge.Catalog{Declared: []forge.Source{src}}, Model: newModel()}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go r.Run(ctx, time.Hour, 10*time.Millisecond)
	select {
	case <-reader.read:
	case <-time.After(2 * time.Second):
		t.Fatal("a failed first read waited for the full period")
	}
}

// A repository created on the forge is read from the next cycle with no new
// declaration, and a listing that fails leaves the last set read (AC1).
func TestReconcileReadsAnOwnersListedRepositories(t *testing.T) {
	lister := &fakeLister{repos: map[string][]string{"o": {"a"}}}
	model := newModel()
	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": &fakeReader{}},
		Catalog: &forge.Catalog{Declared: []forge.Source{{Forge: "github", Owner: "o", Repo: forge.EveryRepo}},
			Listers: map[string]forge.Lister{"github": lister}},
		Model: model,
	}
	r.Once(context.Background())
	lister.repos["o"] = []string{"a", "new"}
	r.Once(context.Background())
	if _, ok := model.saved["github:o/new"]; !ok {
		t.Fatalf("a new repository was not read: %v", model.saved)
	}
	lister.err = errors.New("down")
	delete(model.saved, "github:o/new")
	r.Once(context.Background())
	if _, ok := model.saved["github:o/new"]; !ok {
		t.Fatalf("a failed listing stopped the reads: %v", model.saved)
	}
}

// The start-up seed can find the store unreachable (#3247). The reconcile asks
// again on its next cycle while a wildcard has neither a listing nor a seed, so a
// forge that cannot be listed still serves what was read before.
func TestReconcileSeedsAWildcardTheStartCouldNotSeed(t *testing.T) {
	lister := &fakeLister{err: errors.New("down")}
	model := newModel()
	var asked int
	known := []forge.Source{{Forge: "github", Owner: "o", Repo: "kept"}}
	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": &fakeReader{}},
		Catalog: &forge.Catalog{Declared: []forge.Source{{Forge: "github", Owner: "o", Repo: forge.EveryRepo}},
			Listers: map[string]forge.Lister{"github": lister}},
		Model: model,
		Known: func(context.Context) ([]forge.Source, error) {
			asked++
			if asked == 1 {
				return nil, errors.New("connection refused")
			}
			return known, nil
		},
	}
	r.Once(context.Background())
	if _, ok := model.saved["github:o/kept"]; ok {
		t.Fatalf("read a source nothing had listed or seeded")
	}
	r.Once(context.Background())
	if _, ok := model.saved["github:o/kept"]; !ok {
		t.Fatalf("the second cycle did not seed from the store: %v", model.saved)
	}
	r.Once(context.Background())
	if asked != 2 {
		t.Fatalf("asked the store %d times; a seeded wildcard must not ask again", asked)
	}
}

func TestReconcileDoesNotAskTheStoreOnceListed(t *testing.T) {
	lister := &fakeLister{repos: map[string][]string{"o": {"a"}}}
	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": &fakeReader{}},
		Catalog: &forge.Catalog{Declared: []forge.Source{{Forge: "github", Owner: "o", Repo: forge.EveryRepo}},
			Listers: map[string]forge.Lister{"github": lister}},
		Model: newModel(),
		Known: func(context.Context) ([]forge.Source, error) {
			t.Fatal("asked the store although the listing succeeded")
			return nil, nil
		},
	}
	r.Once(context.Background())
}
