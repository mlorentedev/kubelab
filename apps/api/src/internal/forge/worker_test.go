package forge_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The worker's decisions, without a database: which call it makes, in which order, and what it
// asks its store to record. The loop against Postgres and a forge over HTTP is in the store's tests.

type memStore struct {
	rows  []*forge.Queued
	calls []string
	until time.Time
	retry time.Time
	// hold is what the last claim kept the row out of reach for.
	hold  time.Duration
	adopt bool
	// order is the sequence of store and writer calls, to hold "stamp before send".
	order *[]string
}

func (m *memStore) note(s string) {
	m.calls = append(m.calls, s)
	if m.order != nil {
		*m.order = append(*m.order, "store:"+s)
	}
}

func (m *memStore) Claim(_ context.Context, _ time.Time, hold time.Duration) (*forge.Queued, error) {
	m.hold = hold
	if len(m.rows) == 0 {
		return nil, nil
	}
	q := m.rows[0]
	m.rows = m.rows[1:]
	return q, nil
}
func (m *memStore) Restamp(_ context.Context, _ int64, until time.Time) error {
	m.note("restamp")
	m.until = until
	return nil
}
func (m *memStore) Applied(_ context.Context, _ forge.Queued, _ forge.Result, adopted bool, _ time.Time) error {
	m.note("applied")
	m.adopt = adopted
	return nil
}
func (m *memStore) Refused(context.Context, forge.Queued, forge.Result, time.Time) error {
	m.note("refused")
	return nil
}
func (m *memStore) Retry(_ context.Context, _ forge.Queued, _ forge.Result, next, _ time.Time) error {
	m.note("retry")
	m.retry = next
	return nil
}
func (m *memStore) Unresolved(context.Context, forge.Queued, forge.Result, time.Time) error {
	m.note("unresolved")
	return nil
}
func (m *memStore) Defer(_ context.Context, _ forge.Queued, _ error, next time.Time) error {
	m.note("defer")
	m.retry = next
	return nil
}

type scriptedWriter struct {
	write  forge.Result
	found  forge.LookupResult
	lookup error
	order  *[]string
	writes int
	finds  int
	lk     forge.Lookup
}

func (w *scriptedWriter) Write(context.Context, forge.Write) forge.Result {
	w.writes++
	if w.order != nil {
		*w.order = append(*w.order, "writer:write")
	}
	return w.write
}

func (w *scriptedWriter) FindCreated(_ context.Context, lk forge.Lookup) (forge.LookupResult, error) {
	w.finds++
	w.lk = lk
	if w.order != nil {
		*w.order = append(*w.order, "writer:find")
	}
	return w.found, w.lookup
}

var epoch = time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)

func newWorker(rows []*forge.Queued, w *scriptedWriter) (*forge.Worker, *memStore) {
	st := &memStore{rows: rows}
	return &forge.Worker{
		Store: st, Writers: map[string]forge.Writer{"gitea": w}, Now: func() time.Time { return epoch },
		Settle: 2 * time.Minute, CallTimeout: 10 * time.Second,
	}, st
}

func create(resumed bool) *forge.Queued {
	return &forge.Queued{ID: 5, Action: forge.ActionCreate, Source: forge.Source{Forge: "gitea", Owner: "o", Repo: "r"},
		Payload: forge.Payload{Title: "t"}, Attempts: 1, CreatedAt: epoch.Add(-time.Hour), Resumed: resumed}
}

func label(resumed bool) *forge.Queued {
	return &forge.Queued{ID: 6, Action: forge.ActionAddLabel, Source: forge.Source{Forge: "gitea", Owner: "o", Repo: "r"},
		Number: 3, Payload: forge.Payload{Label: "status:blocked"}, Attempts: 1, CreatedAt: epoch, Resumed: resumed}
}

func TestBackoffDoublesFromTenSecondsToAQuarterHour(t *testing.T) {
	want := []time.Duration{10 * time.Second, 20 * time.Second, 40 * time.Second, 80 * time.Second, 160 * time.Second,
		320 * time.Second, 640 * time.Second, 15 * time.Minute, 15 * time.Minute}
	for i, w := range want {
		if got := forge.Backoff(i + 1); got != w {
			t.Errorf("Backoff(%d) = %s, want %s", i+1, got, w)
		}
	}
	if forge.Backoff(0) != 10*time.Second || forge.Backoff(1_000_000) != 15*time.Minute {
		t.Error("an attempt count out of range must not overflow the schedule")
	}
}

// The marker search is only sound once the original request has ended, so a settle interval that
// does not exceed the call timeout is a configuration the worker refuses to run with.
func TestTheWorkerRefusesASettleIntervalThatDoesNotExceedTheCallTimeout(t *testing.T) {
	for _, settle := range []time.Duration{5 * time.Second, 10 * time.Second} {
		w, _ := newWorker([]*forge.Queued{create(false)}, &scriptedWriter{})
		w.Settle = settle
		if _, err := w.Once(context.Background()); err == nil || !strings.Contains(err.Error(), "settle") {
			t.Errorf("settle %s with a 10s timeout: err = %v, want a refusal", settle, err)
		}
	}
	if forge.SettleInterval <= forge.CallTimeout {
		t.Fatal("the defaults break the same rule")
	}
}

func TestARowIsRestampedBeforeAnyPostThatFollowsANotFound(t *testing.T) {
	var order []string
	sw := &scriptedWriter{write: forge.Result{Outcome: forge.OutcomeApplied, Status: 201, Number: 9}, order: &order}
	w, st := newWorker([]*forge.Queued{create(true)}, sw)
	st.order = &order
	if _, err := w.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(order, " "); got != "writer:find store:restamp writer:write store:applied" {
		t.Fatalf("order = %s, want the search, the stamp, then the post", got)
	}
	if want := epoch.Add(2*time.Minute + 10*time.Second); !st.until.Equal(want) {
		t.Fatalf("stamped until %s, want now+timeout+settle %s", st.until, want)
	}
	// The search lists from the row's creation: an earlier time than any send can only list more.
	if !sw.lk.SentAt.Equal(epoch.Add(-time.Hour)) || sw.lk.Settle != 2*time.Minute || sw.lk.OutboxID != 5 {
		t.Fatalf("lookup = %+v", sw.lk)
	}
}

func TestAFoundCreateIsAdoptedAndNeverPostedAgain(t *testing.T) {
	sw := &scriptedWriter{found: forge.LookupResult{Found: true, Number: 12, URL: "u"}}
	w, st := newWorker([]*forge.Queued{create(true)}, sw)
	if _, err := w.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if sw.writes != 0 || strings.Join(st.calls, " ") != "applied" || !st.adopt {
		t.Fatalf("writes %d, calls %v, adopted %v: want the issue adopted with no post", sw.writes, st.calls, st.adopt)
	}
}

// A search that cannot answer leaves the row for a later look. Posting on a doubt is how a
// second issue is opened.
func TestASearchThatCannotAnswerNeverPosts(t *testing.T) {
	t.Run("not settled: look again when the forge says", func(t *testing.T) {
		until := epoch.Add(90 * time.Second)
		sw := &scriptedWriter{lookup: &forge.NotSettledError{Until: until}}
		w, st := newWorker([]*forge.Queued{create(true)}, sw)
		_, _ = w.Once(context.Background())
		if sw.writes != 0 || strings.Join(st.calls, " ") != "defer" || !st.retry.Equal(until) {
			t.Fatalf("writes %d, calls %v, next %s: want a deferral to %s", sw.writes, st.calls, st.retry, until)
		}
	})
	t.Run("an error: back off, post nothing", func(t *testing.T) {
		sw := &scriptedWriter{lookup: errors.New("listing failed")}
		w, st := newWorker([]*forge.Queued{create(true)}, sw)
		_, _ = w.Once(context.Background())
		if sw.writes != 0 || strings.Join(st.calls, " ") != "defer" || !st.retry.Equal(epoch.Add(forge.Backoff(1))) {
			t.Fatalf("writes %d, calls %v, next %s", sw.writes, st.calls, st.retry)
		}
	})
}

// Only a create is resolved by its marker. A label or a close that was in flight is repeated.
func TestAResumedWriteThatIsNotACreateIsSentAgainWithoutASearch(t *testing.T) {
	sw := &scriptedWriter{write: forge.Result{Outcome: forge.OutcomeApplied, Status: 200}}
	w, st := newWorker([]*forge.Queued{label(true)}, sw)
	_, _ = w.Once(context.Background())
	if sw.finds != 0 || sw.writes != 1 || strings.Join(st.calls, " ") != "applied" {
		t.Fatalf("finds %d, writes %d, calls %v", sw.finds, sw.writes, st.calls)
	}
}

func TestEachClassIsSettledAsItsOwn(t *testing.T) {
	for _, c := range []struct {
		name string
		row  *forge.Queued
		res  forge.Result
		want string
	}{
		{"applied", label(false), forge.Result{Outcome: forge.OutcomeApplied, Status: 200}, "applied"},
		{"failed is terminal", label(false), forge.Result{Outcome: forge.OutcomeFailed, Status: 404}, "refused"},
		{"retry goes back to pending", label(false), forge.Result{Outcome: forge.OutcomeRetry, Status: 503}, "retry"},
		{"a create of unknown outcome stays in flight", create(false), forge.Result{Outcome: forge.OutcomeUnknown}, "unresolved"},
		// Only a create takes the unknown class; anything else that reports it is repeated.
		{"unknown for another action is a retry", label(false), forge.Result{Outcome: forge.OutcomeUnknown}, "retry"},
	} {
		t.Run(c.name, func(t *testing.T) {
			w, st := newWorker([]*forge.Queued{c.row}, &scriptedWriter{write: c.res})
			if _, err := w.Once(context.Background()); err != nil {
				t.Fatal(err)
			}
			if got := strings.Join(st.calls, " "); got != c.want {
				t.Fatalf("calls = %q, want %q", got, c.want)
			}
		})
	}
}

func TestARetryWaitsForTheForgeWhenItAsksForLongerThanTheBackoff(t *testing.T) {
	for _, c := range []struct {
		name       string
		retryAfter time.Duration
		want       time.Duration
	}{
		{"shorter than the backoff: the backoff", 2 * time.Second, forge.Backoff(1)},
		{"longer: the forge's wait", 5 * time.Minute, 5 * time.Minute},
		{"absurd: capped at an hour", 72 * time.Hour, time.Hour},
	} {
		t.Run(c.name, func(t *testing.T) {
			w, st := newWorker([]*forge.Queued{label(false)},
				&scriptedWriter{write: forge.Result{Outcome: forge.OutcomeRetry, Status: 429, RetryAfter: c.retryAfter}})
			_, _ = w.Once(context.Background())
			if want := epoch.Add(c.want); !st.retry.Equal(want) {
				t.Fatalf("next attempt %s, want %s", st.retry, want)
			}
		})
	}
}

func TestARowForAForgeWithNoWriterIsKeptAndNothingIsSent(t *testing.T) {
	sw := &scriptedWriter{}
	w, st := newWorker([]*forge.Queued{label(false)}, sw)
	w.Writers = map[string]forge.Writer{} // the gate is off
	if _, err := w.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if sw.writes != 0 || sw.finds != 0 || strings.Join(st.calls, " ") != "defer" {
		t.Fatalf("writes %d, finds %d, calls %v", sw.writes, sw.finds, st.calls)
	}
}

// A forge may keep working on a request after its client gave up, so a claimed row is out of
// every worker's reach for the call's timeout AND the settle interval after it, never the
// interval alone: a second replica would otherwise look for a create while it can still land.
func TestAClaimHoldsTheRowForTheCallTimeoutAndTheSettleInterval(t *testing.T) {
	w, st := newWorker([]*forge.Queued{create(false)}, &scriptedWriter{write: forge.Result{Outcome: forge.OutcomeApplied, Status: 201, Number: 9}})
	if _, err := w.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if want := 2*time.Minute + 10*time.Second; st.hold != want {
		t.Fatalf("a claim holds the row for %s, want the timeout and the settle interval, %s", st.hold, want)
	}
}
