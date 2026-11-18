package store_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
)

// The write path from the outbox to the confirmed row (CONSOLE-004 AC2, ADR-066 W1-W9): the real
// GiteaWriter against a fake Gitea over HTTP, and the real store on Postgres. These hold the loop,
// including what survives a crash, because the guarantees live in the SQL and in the order of
// commits, not in any one function.

type testClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *testClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *testClock) Advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

const (
	testSettle  = 2 * time.Minute
	testTimeout = 300 * time.Millisecond
)

var gitea = forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}

// sendSnap is the outbox row as the database showed it at the moment a write reached the forge.
type sendSnap struct {
	ID       int64
	Status   string
	Next     time.Time
	Attempts int
}

type loop struct {
	t      *testing.T
	mu     sync.Mutex
	sends  []sendSnap
	ctx    context.Context
	conn   *pgx.Conn
	model  store.ForgeModel
	forge  *fakeForge
	clock  *testClock
	worker *forge.Worker
}

func newLoop(t *testing.T) *loop {
	t.Helper()
	ctx, conn := statsConn(t)
	if _, err := conn.Exec(ctx, `TRUNCATE forge_outbox, forge_write_audit, forge_item, forge_source CASCADE`); err != nil {
		t.Fatal(err)
	}
	f := newFakeForge(t)
	// The clock starts ahead of the database's, so a row enqueued now is already due.
	clock := &testClock{t: time.Now().Add(time.Hour)}
	model := store.ForgeModel{Conf: testPostgres(t)}
	writers := map[string]forge.Writer{"gitea": &forge.GiteaWriter{
		BaseURL: f.srv.URL, Token: "write-token", HTTP: &http.Client{}, Now: clock.Now,
	}}
	l := &loop{t: t, ctx: ctx, conn: conn, model: model, forge: f, clock: clock, worker: &forge.Worker{
		Store: model, Writers: writers, Now: clock.Now, Settle: testSettle, CallTimeout: testTimeout,
	}}
	// Every write that reaches the forge is preceded by a look at the row from a connection of its
	// own, so what the database showed AT THAT MOMENT is held, not what it shows afterwards.
	snap, err := pgx.Connect(ctx, testPostgres(t).DSN())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { snap.Close(ctx) })
	f.set(func(f *fakeForge) {
		f.onWrite = func() {
			rows, err := snap.Query(ctx, `SELECT id, status, next_attempt_at, attempts FROM forge_outbox ORDER BY id`)
			if err != nil {
				t.Error(err)
				return
			}
			defer rows.Close()
			l.mu.Lock()
			defer l.mu.Unlock()
			for rows.Next() {
				var s sendSnap
				if err := rows.Scan(&s.ID, &s.Status, &s.Next, &s.Attempts); err != nil {
					t.Error(err)
					return
				}
				l.sends = append(l.sends, s)
			}
		}
	})
	return l
}

// sentFrom returns the snapshots of one row, one per write that reached the forge.
func (l *loop) sentFrom(id int64) []sendSnap {
	l.mu.Lock()
	defer l.mu.Unlock()
	var out []sendSnap
	for _, s := range l.sends {
		if s.ID == id {
			out = append(out, s)
		}
	}
	return out
}

// committedBeforeTheSend holds W4 and W8: when the write reached the forge, the row was already
// in_flight in the database, stamped no earlier than the clock plus the settle interval.
func (l *loop) committedBeforeTheSend(id int64, sends int, attempts ...int) {
	l.t.Helper()
	got := l.sentFrom(id)
	if len(got) != sends {
		l.t.Fatalf("outbox %d: %d writes reached the forge, want %d", id, len(got), sends)
	}
	for i, s := range got {
		if s.Status != "in_flight" || s.Next.Before(l.clock.Now().Add(testSettle)) || s.Attempts != attempts[i] {
			l.t.Fatalf("outbox %d, write %d: the database showed %+v, want in_flight, stamped >= %s, attempt %d",
				id, i+1, s, l.clock.Now().Add(testSettle), attempts[i])
		}
	}
}

func (l *loop) enqueue(actor, key string, action forge.Action, number int, p forge.Payload) forge.Receipt {
	l.t.Helper()
	r, err := l.model.Enqueue(l.ctx, forge.Enqueue{
		Actor: actor, Key: key, Hash: "h-" + key, Action: action, Source: gitea, Number: number, Payload: p,
	})
	if err != nil {
		l.t.Fatal(err)
	}
	return r
}

func (l *loop) run() int {
	l.t.Helper()
	n, err := l.worker.Once(l.ctx)
	if err != nil {
		l.t.Fatal(err)
	}
	return n
}

type row struct {
	Status   string
	Attempts int
	Next     time.Time
	Number   *int
	Response string
	Err      string
}

func (l *loop) row(id int64) row {
	l.t.Helper()
	var r row
	var response, lastErr *string
	if err := l.conn.QueryRow(l.ctx, `SELECT status, attempts, next_attempt_at, number, response::text, last_error
		FROM forge_outbox WHERE id = $1`, id).Scan(&r.Status, &r.Attempts, &r.Next, &r.Number, &response, &lastErr); err != nil {
		l.t.Fatal(err)
	}
	if response != nil {
		r.Response = *response
	}
	if lastErr != nil {
		r.Err = *lastErr
	}
	return r
}

// audit lists "outcome/status" of the audit rows of one outbox row, oldest first.
func (l *loop) audit(id int64) []string {
	l.t.Helper()
	rows, err := l.conn.Query(l.ctx, `SELECT outcome, forge_status FROM forge_write_audit WHERE outbox_id = $1 ORDER BY id`, id)
	if err != nil {
		l.t.Fatal(err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var outcome string
		var status *int
		if err := rows.Scan(&outcome, &status); err != nil {
			l.t.Fatal(err)
		}
		if status == nil {
			out = append(out, outcome+"/-")
		} else {
			out = append(out, outcome+"/"+itoa(*status))
		}
	}
	return out
}

func itoa(n int) string { b, _ := json.Marshal(n); return string(b) }

// item reads the read model's row of issue n: state and labels.
func (l *loop) item(n int) (state string, labels []string, ok bool) {
	l.t.Helper()
	err := l.conn.QueryRow(l.ctx, `SELECT state, labels FROM forge_item
		WHERE forge = 'gitea' AND owner = 'o' AND repo = 'r' AND number = $1`, n).Scan(&state, &labels)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil, false
	}
	if err != nil {
		l.t.Fatal(err)
	}
	return state, labels, true
}

// known puts an issue in the read model, as a reconcile would have.
func (l *loop) known(n int, labels ...string) {
	l.t.Helper()
	if _, err := l.conn.Exec(l.ctx, `INSERT INTO forge_source (forge, owner, repo) VALUES ('gitea', 'o', 'r')
		ON CONFLICT DO NOTHING`); err != nil {
		l.t.Fatal(err)
	}
	if labels == nil {
		labels = []string{}
	}
	if _, err := l.conn.Exec(l.ctx, `INSERT INTO forge_item (forge, owner, repo, number, kind, title, state, author, labels, url, updated_at)
		VALUES ('gitea', 'o', 'r', $1, 'issue', 't', 'open', 'a', $2, 'u', now())`, n, labels); err != nil {
		l.t.Fatal(err)
	}
}

// --- idempotency (W1) -------------------------------------------------------------------

func TestEnqueueReplayReturnsTheEarlierRowAndWritesNone(t *testing.T) {
	l := newLoop(t)
	first := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	again := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	if first.Replay || !again.Replay || again.ID != first.ID {
		t.Fatalf("first %+v, again %+v: want the same row, the second marked a replay", first, again)
	}
	var rows int
	if err := l.conn.QueryRow(l.ctx, `SELECT count(*) FROM forge_outbox`).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("rows = %d (%v), want 1", rows, err)
	}
}

func TestEnqueueRefusesTheSameKeyWithAnotherRequest(t *testing.T) {
	l := newLoop(t)
	l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	_, err := l.model.Enqueue(l.ctx, forge.Enqueue{
		Actor: "manu", Key: "k1", Hash: "another", Action: forge.ActionCreate, Source: gitea, Payload: forge.Payload{Title: "other"},
	})
	if !errors.Is(err, forge.ErrKeyReuse) {
		t.Fatalf("err = %v, want ErrKeyReuse", err)
	}
	var rows int
	if err := l.conn.QueryRow(l.ctx, `SELECT count(*) FROM forge_outbox`).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("rows = %d (%v), a refused key must write nothing", rows, err)
	}
}

func TestEnqueueKeysBelongToTheirActor(t *testing.T) {
	l := newLoop(t)
	a := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	b := l.enqueue("machine", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	if a.ID == b.ID || b.Replay {
		t.Fatalf("another actor's key met this actor's row: %+v %+v", a, b)
	}
}

func TestSimultaneousEnqueuesOfOneKeyMakeOneRow(t *testing.T) {
	l := newLoop(t)
	var wg sync.WaitGroup
	ids := make([]int64, 8)
	for i := range ids {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, err := l.model.Enqueue(l.ctx, forge.Enqueue{
				Actor: "manu", Key: "race", Hash: "h", Action: forge.ActionCreate, Source: gitea, Payload: forge.Payload{Title: "t"},
			})
			if err != nil {
				t.Error(err)
			}
			ids[i] = r.ID
		}()
	}
	wg.Wait()
	for _, id := range ids {
		if id != ids[0] {
			t.Fatalf("ids = %v, want one row", ids)
		}
	}
}

// --- the loop ---------------------------------------------------------------------------

func TestACreateIsAppliedAndAppearsInTheReadModel(t *testing.T) {
	l := newLoop(t)
	r := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "a task", Body: "SECRET-BODY-TEXT"})
	if got := l.row(r.ID).Status; got != "pending" {
		t.Fatalf("before the worker runs the row is %q, want pending", got)
	}
	if l.run() != 1 {
		t.Fatal("the worker took no row")
	}
	got := l.row(r.ID)
	if got.Status != "applied" || got.Number == nil || *got.Number != 1 || !strings.Contains(got.Response, `"number": 1`) {
		t.Fatalf("row = %+v, want applied as issue 1 with its response stored", got)
	}
	if issue := l.forge.issue(1); issue == nil || !strings.Contains(issue.Body, forge.Marker(r.ID)) || !strings.HasPrefix(issue.Body, "SECRET-BODY-TEXT") {
		t.Fatalf("the forge's issue = %+v, want the body and the outbox marker", issue)
	}
	if state, _, ok := l.item(1); !ok || state != "open" {
		t.Fatal("W2: the worker applies a confirmed create to the read model; it was left to the webhook")
	}
	if got := l.audit(r.ID); len(got) != 1 || got[0] != "applied/201" {
		t.Fatalf("audit = %v, want one applied/201", got)
	}
	l.committedBeforeTheSend(r.ID, 1, 1)
	// The record says what was asked and never the issue's body.
	var leaked int
	if err := l.conn.QueryRow(l.ctx, `SELECT count(*) FROM forge_write_audit WHERE detail::text LIKE '%SECRET%'`).Scan(&leaked); err != nil || leaked != 0 {
		t.Fatalf("the audit carries the issue body (%d rows, %v)", leaked, err)
	}
	// A replay of the applied write answers with the stored response and calls nothing.
	again := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "a task", Body: "SECRET-BODY-TEXT"})
	if !again.Replay || again.Status != "applied" || !strings.Contains(string(again.Response), `"number"`) {
		t.Fatalf("replay = %+v, want the applied row and its response", again)
	}
	if l.run() != 0 || l.forge.count("POST") != 1 {
		t.Fatal("a replay called the forge again")
	}
}

func TestEveryActionIsAppliedToTheReadModel(t *testing.T) {
	l := newLoop(t)
	n := l.forge.seed("existing", "old")
	l.known(n, "old")
	steps := []struct {
		action  forge.Action
		payload forge.Payload
		check   func(state string, labels []string) bool
	}{
		{forge.ActionAddLabel, forge.Payload{Label: "status:blocked"}, func(_ string, l []string) bool { return hasLabel(l, "status:blocked") }},
		{forge.ActionClose, forge.Payload{}, func(s string, _ []string) bool { return s == "closed" }},
		{forge.ActionReopen, forge.Payload{}, func(s string, _ []string) bool { return s == "open" }},
	}
	for i, s := range steps {
		r := l.enqueue("manu", "k"+itoa(i), s.action, n, s.payload)
		l.run()
		if got := l.row(r.ID).Status; got != "applied" {
			t.Fatalf("%s: row is %q: %s", s.action, got, l.row(r.ID).Err)
		}
		state, labels, _ := l.item(n)
		if !s.check(state, labels) {
			t.Fatalf("%s: read model = %s %v", s.action, state, labels)
		}
	}
}

func hasLabel(labels []string, name string) bool {
	for _, l := range labels {
		if l == name {
			return true
		}
	}
	return false
}

func TestARefusalIsTerminal(t *testing.T) {
	l := newLoop(t)
	// Issue 7 does not exist: the forge answers 404, which no retry can change.
	r := l.enqueue("manu", "k1", forge.ActionClose, 7, forge.Payload{})
	l.run()
	got := l.row(r.ID)
	if got.Status != "failed" || got.Err == "" {
		t.Fatalf("row = %+v, want failed with the forge's message", got)
	}
	l.clock.Advance(24 * time.Hour)
	if l.run() != 0 {
		t.Fatal("a failed row was taken again")
	}
	if a := l.audit(r.ID); len(a) != 1 || a[0] != "failed/404" {
		t.Fatalf("audit = %v, want one failed/404", a)
	}
}

func TestAServerErrorIsRetriedWithBackoffAndEveryCallIsAudited(t *testing.T) {
	l := newLoop(t)
	n := l.forge.seed("existing")
	l.known(n)
	var calls int
	l.forge.set(func(f *fakeForge) {
		f.fail = func(method, path string) int {
			calls++
			if calls <= 2 {
				return http.StatusServiceUnavailable
			}
			return 0
		}
	})
	r := l.enqueue("manu", "k1", forge.ActionAddLabel, n, forge.Payload{Label: "priority:P1"})
	l.run()
	first := l.row(r.ID)
	if first.Status != "pending" || first.Attempts != 1 || !first.Next.Equal(l.clock.Now().Add(forge.Backoff(1))) {
		t.Fatalf("after the first 503: %+v, want pending, one attempt, due in %s", first, forge.Backoff(1))
	}
	if l.run() != 0 {
		t.Fatal("the row was taken before its backoff passed")
	}
	l.clock.Advance(forge.Backoff(1))
	l.run()
	second := l.row(r.ID)
	if second.Status != "pending" || second.Attempts != 2 || !second.Next.Equal(l.clock.Now().Add(forge.Backoff(2))) {
		t.Fatalf("after the second 503: %+v, want the backoff to double", second)
	}
	if forge.Backoff(2) <= forge.Backoff(1) {
		t.Fatal("the backoff does not grow")
	}
	l.clock.Advance(forge.Backoff(2))
	l.run()
	if got := l.row(r.ID); got.Status != "applied" || got.Err != "" {
		t.Fatalf("row = %+v, want applied once the forge answered", got)
	}
	if a := l.audit(r.ID); strings.Join(a, " ") != "retry/503 retry/503 applied/200" {
		t.Fatalf("audit = %v, want one row per forge call (W9)", a)
	}
}

// --- ordering (per issue) ---------------------------------------------------------------

func TestWritesToOneIssueKeepTheirOrderAndNeverOverlap(t *testing.T) {
	l := newLoop(t)
	n := l.forge.seed("existing")
	l.known(n)
	var failed bool
	l.forge.set(func(f *fakeForge) {
		f.fail = func(method, path string) int {
			if method == http.MethodPost && strings.HasSuffix(path, "/labels") && !failed {
				failed = true
				return http.StatusServiceUnavailable
			}
			return 0
		}
	})
	label := l.enqueue("manu", "a", forge.ActionAddLabel, n, forge.Payload{Label: "status:blocked"})
	closing := l.enqueue("manu", "b", forge.ActionClose, n, forge.Payload{})

	l.run() // the label meets a 503 and backs off; the close must not leapfrog it
	if l.forge.count("PATCH") != 0 {
		t.Fatal("the close was sent while an earlier write to the same issue was owed")
	}
	if got := l.row(closing.ID).Status; got != "pending" {
		t.Fatalf("the close is %q, want it untouched", got)
	}
	l.clock.Advance(forge.Backoff(1))
	l.run()
	if l.row(label.ID).Status != "applied" || l.row(closing.ID).Status != "applied" {
		t.Fatalf("label %q, close %q, want both applied in order", l.row(label.ID).Status, l.row(closing.ID).Status)
	}
	reqs := l.forge.sent()
	if last := reqs[len(reqs)-1]; !strings.HasPrefix(last, "PATCH") {
		t.Fatalf("requests = %v, the close must come after the label", reqs)
	}
}

func TestOneIssueHasOneClaimAtATimeAcrossWorkers(t *testing.T) {
	l := newLoop(t)
	for _, k := range []string{"a", "b", "c"} {
		l.enqueue("manu", k, forge.ActionAddLabel, 1, forge.Payload{Label: "status:blocked"})
	}
	claims := claimConcurrently(t, l, 6)
	if len(claims) != 1 {
		t.Fatalf("%d rows of one issue were claimed at once, want 1", len(claims))
	}
	// Settled, the next one is free.
	if err := l.model.Applied(l.ctx, claims[0], forge.Result{Outcome: forge.OutcomeApplied, Status: 200}, false, l.clock.Now()); err != nil {
		t.Fatal(err)
	}
	if next, err := l.model.Claim(l.ctx, l.clock.Now(), testSettle); err != nil || next == nil || next.ID <= claims[0].ID {
		t.Fatalf("next claim = %+v, %v, want the following row", next, err)
	}
}

func TestRowsOfDifferentWorkersAreNeverTheSameRow(t *testing.T) {
	l := newLoop(t)
	for _, k := range []string{"a", "b", "c", "d", "e", "f"} {
		l.enqueue("manu", k, forge.ActionCreate, 0, forge.Payload{Title: k})
	}
	claims := claimConcurrently(t, l, 6)
	if len(claims) != 6 {
		t.Fatalf("%d of 6 creates were claimed by 6 workers, want one each", len(claims))
	}
	seen := map[int64]bool{}
	for _, c := range claims {
		if seen[c.ID] {
			t.Fatalf("row %d was claimed twice", c.ID)
		}
		seen[c.ID] = true
	}
}

// SKIP LOCKED is what keeps one worker from waiting on another's row: a row someone else holds is
// passed over, and the claim returns the next one (or nothing) at once.
func TestAClaimPassesOverARowAnotherWorkerHolds(t *testing.T) {
	l := newLoop(t)
	first := l.enqueue("manu", "a", forge.ActionCreate, 0, forge.Payload{Title: "a"})
	second := l.enqueue("manu", "b", forge.ActionCreate, 0, forge.Payload{Title: "b"})
	tx, err := l.conn.Begin(l.ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(l.ctx)
	if _, err := tx.Exec(l.ctx, `SELECT id FROM forge_outbox WHERE id = $1 FOR UPDATE`, first.ID); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(l.ctx, 3*time.Second)
	defer cancel()
	q, err := l.model.Claim(ctx, l.clock.Now(), testSettle)
	if err != nil || q == nil || q.ID != second.ID {
		t.Fatalf("claim = %+v, %v, want the second row without waiting for the first", q, err)
	}
}

// claimConcurrently makes n workers claim at once and returns the rows they got.
func claimConcurrently(t *testing.T, l *loop, n int) []forge.Queued {
	t.Helper()
	var wg sync.WaitGroup
	var mu sync.Mutex
	var got []forge.Queued
	start := make(chan struct{})
	for range n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			q, err := l.model.Claim(l.ctx, l.clock.Now(), testSettle)
			if err != nil {
				t.Error(err)
				return
			}
			if q != nil {
				mu.Lock()
				got = append(got, *q)
				mu.Unlock()
			}
		}()
	}
	close(start)
	wg.Wait()
	sort.Slice(got, func(i, j int) bool { return got[i].ID < got[j].ID })
	return got
}

// --- the settle schedule (W8) -----------------------------------------------------------

func TestAClaimedRowIsNotDueAgainBeforeTheSettleInterval(t *testing.T) {
	l := newLoop(t)
	r := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	t0 := l.clock.Now()
	q, err := l.model.Claim(l.ctx, t0, testSettle)
	if err != nil || q == nil || q.Resumed || q.Attempts != 1 {
		t.Fatalf("claim = %+v, %v, want a first attempt", q, err)
	}
	if got := l.row(r.ID); got.Status != "in_flight" || !got.Next.Equal(t0.Add(testSettle)) {
		t.Fatalf("after the claim: %+v, want in_flight stamped at claim + settle", got)
	}
	if again, _ := l.model.Claim(l.ctx, t0.Add(testSettle-time.Second), testSettle); again != nil {
		t.Fatal("a row in flight was claimed again before its interval passed")
	}
	// A stamp never moves earlier, so nothing can shorten the interval after the send.
	if err := l.model.Restamp(l.ctx, r.ID, t0); err != nil {
		t.Fatal(err)
	}
	if again, _ := l.model.Claim(l.ctx, t0.Add(testSettle-time.Second), testSettle); again != nil {
		t.Fatal("a restamp to an earlier time shortened the interval")
	}
	if err := l.model.Defer(l.ctx, *q, errors.New("lookup failed"), t0); err != nil {
		t.Fatal(err)
	}
	if again, _ := l.model.Claim(l.ctx, t0.Add(testSettle-time.Second), testSettle); again != nil {
		t.Fatal("a deferral to an earlier time shortened the interval")
	}
	resumed, err := l.model.Claim(l.ctx, t0.Add(testSettle), testSettle)
	// One attempt for the claim and one the Restamp above counted: resuming a row to look at it
	// adds none (the crash test below holds that on a row nothing else touched).
	if err != nil || resumed == nil || !resumed.Resumed || resumed.ID != r.ID || resumed.Attempts != 2 {
		t.Fatalf("after the interval: %+v, %v, want the same row, resumed", resumed, err)
	}
}

func TestACreateWhoseAnswerWasLostIsFoundByItsMarkerAndNotPostedAgain(t *testing.T) {
	l := newLoop(t)
	// The forge takes longer than the client waits, and makes the issue anyway.
	l.forge.set(func(f *fakeForge) { f.createDelay = 3 * testTimeout })
	r := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "slow"})
	l.run()
	got := l.row(r.ID)
	if got.Status != "in_flight" || got.Err == "" {
		t.Fatalf("after the timeout: %+v, want in_flight with the error kept", got)
	}
	if a := l.audit(r.ID); len(a) != 1 || a[0] != "unknown/-" {
		t.Fatalf("audit = %v, want one unknown call with no forge status", a)
	}
	// The original request finishes after the client gave up and before the search.
	waitFor(t, func() bool { return l.forge.issueCount() == 1 })
	if l.run() != 0 {
		t.Fatal("the row was looked at before the settle interval passed")
	}
	l.clock.Advance(testSettle)
	if l.run() != 1 {
		t.Fatal("the row was not resumed once its interval passed")
	}
	got = l.row(r.ID)
	if got.Status != "applied" || got.Number == nil || *got.Number != 1 {
		t.Fatalf("row = %+v, want applied as the issue the forge made", got)
	}
	if n := l.forge.issueCount(); n != 1 || l.forge.count("POST") != 1 {
		t.Fatalf("the forge holds %d issues after %d creates, want exactly one", n, l.forge.count("POST"))
	}
	if state, _, ok := l.item(1); !ok || state != "open" {
		t.Fatal("an adopted create is applied to the read model like any other")
	}
	if a := strings.Join(l.audit(r.ID), " "); a != "unknown/- applied/-" {
		t.Fatalf("audit = %q, want the unknown call then the adoption, with no status", a)
	}
}

func TestACreateTheForgeNeverMadeIsPostedAgainAfterTheInterval(t *testing.T) {
	l := newLoop(t)
	l.forge.set(func(f *fakeForge) { f.dropCreate = true })
	r := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "lost"})
	l.run()
	if got := l.row(r.ID).Status; got != "in_flight" {
		t.Fatalf("row is %q, want in_flight after a connection that ended with no answer", got)
	}
	l.forge.set(func(f *fakeForge) { f.dropCreate = false })
	l.clock.Advance(testSettle)
	l.run()
	got := l.row(r.ID)
	if got.Status != "applied" || got.Attempts != 2 {
		t.Fatalf("row = %+v, want applied by a second post after the search found nothing", got)
	}
	if l.forge.issueCount() != 1 {
		t.Fatalf("the forge holds %d issues, want 1", l.forge.issueCount())
	}
	// The second post was stamped, and counted, before it was sent (the clock moved by one interval).
	second := l.sentFrom(r.ID)[1:]
	if len(second) != 1 || second[0].Status != "in_flight" || second[0].Attempts != 2 || second[0].Next.Before(l.clock.Now().Add(testSettle)) {
		t.Fatalf("at the second post the database showed %+v, want in_flight, attempt 2, stamped a full interval ahead", second)
	}
}

// A crash between the forge's 2xx and the commit that records it: the issue exists and the row
// does not know. A fresh process finds it by its marker and opens no second one.
type diesBeforeTheCommit struct{ forge.OutboxStore }

func (diesBeforeTheCommit) Applied(context.Context, forge.Queued, forge.Result, bool, time.Time) error {
	return errors.New("the process ended before the commit")
}

func TestACrashBetweenTheForgeAndTheCommitOpensNoSecondIssue(t *testing.T) {
	l := newLoop(t)
	r := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "once"})
	dying := *l.worker
	dying.Store = diesBeforeTheCommit{l.model}
	if _, err := dying.Once(l.ctx); err != nil {
		t.Fatal(err)
	}
	if l.forge.issueCount() != 1 || l.row(r.ID).Status != "in_flight" {
		t.Fatalf("setup: %d issues, row %q, want the issue made and the row still in flight", l.forge.issueCount(), l.row(r.ID).Status)
	}
	// A restart: a new worker over the same database. Not due until the interval has passed.
	restarted := &forge.Worker{Store: l.model, Writers: l.worker.Writers, Now: l.clock.Now, Settle: testSettle, CallTimeout: testTimeout}
	if n, _ := restarted.Once(l.ctx); n != 0 {
		t.Fatal("the restarted worker took the row before its interval passed")
	}
	l.clock.Advance(testSettle)
	if n, err := restarted.Once(l.ctx); err != nil || n != 1 {
		t.Fatalf("restarted worker: %d, %v", n, err)
	}
	got := l.row(r.ID)
	if got.Status != "applied" || got.Attempts != 1 || got.Number == nil || *got.Number != 1 || l.forge.issueCount() != 1 || l.forge.count("POST") != 1 {
		t.Fatalf("row %+v, %d issues, %d creates: want the one issue adopted, no second post", got, l.forge.issueCount(), l.forge.count("POST"))
	}
}

// A write that is not a create is safe to repeat, so a row left in flight is sent again.
func TestAnInterruptedLabelIsSentAgain(t *testing.T) {
	l := newLoop(t)
	n := l.forge.seed("existing")
	l.known(n)
	r := l.enqueue("manu", "k1", forge.ActionAddLabel, n, forge.Payload{Label: "status:blocked"})
	dying := *l.worker
	dying.Store = diesBeforeTheCommit{l.model}
	_, _ = dying.Once(l.ctx)
	l.clock.Advance(testSettle)
	l.run()
	if got := l.row(r.ID); got.Status != "applied" || got.Attempts != 2 {
		t.Fatalf("row = %+v, want applied by the second send", got)
	}
}

// --- the gate (W14) ---------------------------------------------------------------------

func TestARowForAForgeWithNoWriterIsNeverSent(t *testing.T) {
	l := newLoop(t)
	l.worker.Writers = forge.NewWriters(forge.Credentials{GiteaURL: l.forge.srv.URL, GiteaWriteToken: "t"}) // gate off
	r := l.enqueue("manu", "k1", forge.ActionCreate, 0, forge.Payload{Title: "t"})
	l.run()
	if l.forge.count("") != 0 {
		t.Fatalf("the forge got %v with no writer configured", l.forge.sent())
	}
	if got := l.row(r.ID); got.Status != "in_flight" || !strings.Contains(got.Err, "no writer") {
		t.Fatalf("row = %+v, want it kept, owed, with the reason", got)
	}
	if a := l.audit(r.ID); len(a) != 0 {
		t.Fatalf("audit = %v: no call was made", a)
	}
}

// --- the schema ----------------------------------------------------------------------

// The audit's CHECK is the set of outcomes the worker can record: an outcome the table refuses
// fails at the insert, in the middle of settling a write, so the two are held equal here.
func TestTheAuditCheckIsTheSetOfOutcomes(t *testing.T) {
	l := newLoop(t)
	var def string
	if err := l.conn.QueryRow(l.ctx, `SELECT pg_get_constraintdef(oid) FROM pg_constraint
		WHERE conname = 'forge_write_audit_outcome_check'`).Scan(&def); err != nil {
		t.Fatal(err)
	}
	var in, out []string
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllStringSubmatch(def, -1) {
		in = append(in, m[1])
	}
	for _, o := range forge.Outcomes {
		out = append(out, string(o))
	}
	sort.Strings(in)
	sort.Strings(out)
	if strings.Join(in, ",") != strings.Join(out, ",") {
		t.Fatalf("audit CHECK %v, outcomes %v", in, out)
	}
}

func TestTheAuditTableNamesWhatItRecords(t *testing.T) {
	l := newLoop(t)
	var comment string
	if err := l.conn.QueryRow(l.ctx, `SELECT obj_description('forge_write_audit'::regclass)`).Scan(&comment); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(comment, "retry") || !strings.Contains(comment, "unknown") {
		t.Fatalf("table comment %q does not say what a row is", comment)
	}
}

func waitFor(t *testing.T, ok func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for !ok() {
		if time.Now().After(deadline) {
			t.Fatal("timed out")
		}
		time.Sleep(10 * time.Millisecond)
	}
}
