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
		Sources: []forge.Source{down, up},
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
	r := forge.Reconciler{Sources: []forge.Source{src}, Model: model}
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
	for _, bad := range []string{"github", "github:o", ":o/r", "github:/r"} {
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
		Sources: []forge.Source{src},
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
		Sources: []forge.Source{up, down},
		Model:   newModel(),
	}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	r.Run(ctx, time.Hour, 5*time.Millisecond)
	if n := broken.count(); n < 3 {
		t.Fatalf("the down source was read %d times in 200ms with a 5ms retry", n)
	}
	if n := healthy.count(); n != 1 {
		t.Fatalf("the healthy source was read %d times while the other was retried", n)
	}
}

func TestFailedCycleRetriesBeforeThePeriod(t *testing.T) {
	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}
	reader := &flakyReader{read: make(chan struct{})}
	r := forge.Reconciler{Readers: map[string]forge.Reader{"github": reader}, Sources: []forge.Source{src}, Model: newModel()}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go r.Run(ctx, time.Hour, 10*time.Millisecond)
	select {
	case <-reader.read:
	case <-time.After(2 * time.Second):
		t.Fatal("a failed first read waited for the full period")
	}
}
