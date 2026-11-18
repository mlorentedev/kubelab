package store_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/console"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The whole write path through its front door (CONSOLE-004 AC2, ADR-066 W1 to W14): the console's
// HTTP routes, the real intake, the real store on Postgres, the worker, the real GiteaWriter and a
// fake Gitea over HTTP. The routes' own table of statuses is in console's tests; what is held here
// is what only the whole loop can show: that the answer a client sees is the state of the row, and
// that nothing it was told is lost to a crash, a retry or a replay.

const operatorHost = "console.kubelab.live"

type routes struct {
	*loop
	r      *gin.Engine
	closed *gin.Engine // the same routes with the gate off: no writer
}

func newRoutes(t *testing.T) *routes {
	t.Helper()
	gin.SetMode(gin.TestMode)
	l := newLoop(t)
	declared := []forge.Source{gitea}
	build := func(writers map[string]forge.Writer) *gin.Engine {
		w := &console.Writes{
			Intake: &forge.Intake{Store: l.model, Kinds: l.model, Writers: writers,
				Sources: func() ([]forge.Source, error) { return declared, nil }},
			Reader: l.model, Now: l.clock.Now,
		}
		r := gin.New()
		console.Register(r, console.Live(l.model, &forge.Catalog{Declared: declared}), func() string { return operatorHost }, nil, w)
		r.POST("/api/forge/issues", w.Machine())
		return r
	}
	return &routes{loop: l, r: build(l.worker.Writers), closed: build(map[string]forge.Writer{})}
}

type reply struct {
	Code int
	ID   int64
	// Status is the receipt's status.
	Status   string
	Response string
	Error    *string
	Raw      string
}

func (x *routes) call(r *gin.Engine, user, key, method, path, body string) reply {
	x.t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Host = operatorHost
	if user != "" {
		req.Header.Set("Remote-User", user)
	}
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	out := reply{Code: w.Code, Raw: w.Body.String()}
	var got struct {
		ID       int64           `json:"id"`
		Status   string          `json:"status"`
		Response json.RawMessage `json:"response"`
		Error    *string         `json:"error"`
	}
	if json.Unmarshal(w.Body.Bytes(), &got) == nil {
		out.ID, out.Status, out.Response, out.Error = got.ID, got.Status, string(got.Response), got.Error
	}
	return out
}

func (x *routes) post(user, key, path, body string) reply {
	return x.call(x.r, user, key, "POST", path, body)
}

const (
	createPath = "/console/issues"
	createBody = `{"source":"gitea:o/r","title":"Renew the certificate","body":"before Friday"}`
)

func itemPath(n int, tail string) string { return "/console/issues/gitea/o/r/" + itoa(n) + tail }

type queued struct {
	ID     int64   `json:"id"`
	Action string  `json:"action"`
	Number *int    `json:"number"`
	Detail string  `json:"detail"`
	Status string  `json:"status"`
	Error  *string `json:"error"`
}

// shown is the queue's `writes`, read from GET /console/queue as the console reads it.
func (x *routes) shown() []queued {
	x.t.Helper()
	req := httptest.NewRequest("GET", "/console/queue", nil)
	req.Host = operatorHost
	w := httptest.NewRecorder()
	x.r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		x.t.Fatalf("queue: %d %s", w.Code, w.Body)
	}
	var page struct {
		Writes []queued `json:"writes"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		x.t.Fatal(err)
	}
	return page.Writes
}

func (x *routes) outboxRows() int {
	x.t.Helper()
	var n int
	if err := x.conn.QueryRow(x.ctx, `SELECT count(*) FROM forge_outbox`).Scan(&n); err != nil {
		x.t.Fatal(err)
	}
	return n
}

func TestACreateGoesFromTheRouteToTheForgeAndItsReplayAnswersWhatHappened(t *testing.T) {
	x := newRoutes(t)
	first := x.post("manu", "k1", createPath, createBody)
	if first.Code != http.StatusAccepted || first.Status != "pending" || first.Response != "null" {
		t.Fatalf("the create: %+v", first)
	}
	if w := x.shown(); len(w) != 1 || w[0].ID != first.ID || w[0].Status != "pending" || w[0].Action != "create" ||
		w[0].Number != nil || w[0].Detail != "Renew the certificate" {
		t.Fatalf("the queue shows %+v, want the create pending with its title", w)
	}
	// Retried before the worker ran: the same row, still pending, no second row.
	if again := x.post("manu", "k1", createPath, createBody); again.Code != http.StatusAccepted || again.ID != first.ID || x.outboxRows() != 1 {
		t.Fatalf("a replay before the worker ran: %+v, %d rows", again, x.outboxRows())
	}

	if x.run() != 1 {
		t.Fatal("the worker took no row")
	}
	if issue := x.forge.issue(1); issue == nil || issue.Title != "Renew the certificate" || !strings.Contains(issue.Body, forge.Marker(first.ID)) {
		t.Fatalf("the forge's issue = %+v", issue)
	}
	if w := x.shown(); len(w) != 0 {
		t.Fatalf("an applied write is still in the queue's writes: %+v", w)
	}
	settled := x.post("manu", "k1", createPath, createBody)
	if settled.Code != http.StatusOK || settled.Status != "applied" || !strings.Contains(settled.Response, `"number":1`) {
		t.Fatalf("the replay of an applied create: %+v, want 200 with the forge's answer", settled)
	}
	if x.forge.count("POST") != 1 || x.outboxRows() != 1 {
		t.Fatalf("a replay reached the forge or wrote a row: %d creates, %d rows", x.forge.count("POST"), x.outboxRows())
	}
}

func TestTheSameKeyOnAnotherBodyOrAnotherIssueIs422AndChangesNothing(t *testing.T) {
	x := newRoutes(t)
	a, b := x.forge.seed("a"), x.forge.seed("b")
	x.known(a)
	x.known(b)
	label := `{"label":"status:in-progress"}`
	first := x.post("manu", "k1", itemPath(a, "/labels"), label)
	if first.Code != http.StatusAccepted {
		t.Fatalf("setup: %+v", first)
	}
	for name, c := range map[string]struct{ path, body string }{
		"another issue":  {itemPath(b, "/labels"), label},
		"another label":  {itemPath(a, "/labels"), `{"label":"status:done"}`},
		"another action": {itemPath(a, "/close"), ``},
	} {
		if got := x.post("manu", "k1", c.path, c.body); got.Code != http.StatusUnprocessableEntity {
			t.Errorf("the key reused for %s: %d %s, want 422", name, got.Code, got.Raw)
		}
	}
	if x.outboxRows() != 1 {
		t.Fatalf("%d rows after the refused reuses, want the first only", x.outboxRows())
	}
	x.run()
	if _, labels, _ := x.item(a); !hasLabel(labels, "status:in-progress") {
		t.Fatalf("labels of the first issue: %v", labels)
	}
	if _, labels, _ := x.item(b); len(labels) != 0 {
		t.Fatalf("the refused request reached the other issue: %v", labels)
	}
}

func TestWithTheGateOffNothingIsEnqueuedOrSent(t *testing.T) {
	x := newRoutes(t)
	n := x.forge.seed("a")
	x.known(n)
	for _, c := range []struct{ method, path, body string }{
		{"POST", createPath, createBody},
		{"POST", itemPath(n, "/labels"), `{"label":"status:x"}`},
		{"DELETE", itemPath(n, "/labels/status:x"), ``},
		{"POST", itemPath(n, "/assignees"), `{"login":"manu"}`},
		{"DELETE", itemPath(n, "/assignees/manu"), ``},
		{"POST", itemPath(n, "/close"), ``},
		{"POST", itemPath(n, "/reopen"), ``},
		{"POST", "/api/forge/issues", createBody},
	} {
		if got := x.call(x.closed, "manu", "k1", c.method, c.path, c.body); got.Code != http.StatusServiceUnavailable {
			t.Errorf("%s %s with the gate off: %d, want 503", c.method, c.path, got.Code)
		}
	}
	if x.outboxRows() != 0 || x.run() != 0 || x.forge.count("POST")+x.forge.count("PUT")+x.forge.count("PATCH")+x.forge.count("DELETE") != 0 {
		t.Fatal("a write was kept or sent with the gate off")
	}
}

func TestARefusalIsShownFailedAndAnswersAsFailedOnReplay(t *testing.T) {
	x := newRoutes(t)
	// Issue 7 does not exist on the forge: a 404, which no retry changes.
	got := x.post("manu", "k1", itemPath(7, "/close"), ``)
	if got.Code != http.StatusAccepted {
		t.Fatalf("a close of an issue the read model has not met: %+v, want it accepted: the forge judges", got)
	}
	x.run()
	w := x.shown()
	if len(w) != 1 || w[0].Status != "failed" || w[0].Error == nil || !strings.Contains(*w[0].Error, "404") || w[0].Number == nil || *w[0].Number != 7 {
		t.Fatalf("the queue shows %+v, want the close as failed with the forge's answer", w)
	}
	replay := x.post("manu", "k1", itemPath(7, "/close"), ``)
	if replay.Code != http.StatusOK || replay.Status != "failed" || replay.Error == nil {
		t.Fatalf("the replay of a failed write: %+v, want 200 failed with its error", replay)
	}
	if n := x.forge.count("PATCH"); n != 1 {
		t.Fatalf("%d closes reached the forge, want the one", n)
	}
}

// The window a failed write stays in the queue is measured from its latest forge call.
func TestAFailedWriteStaysForADayFromItsLastCallAndNotFromItsQueueing(t *testing.T) {
	x := newRoutes(t)
	// An old write that failed just now: queued three days ago, retried until the forge refused it.
	old := x.post("manu", "old", itemPath(7, "/close"), ``)
	x.run()
	if _, err := x.conn.Exec(x.ctx, `UPDATE forge_outbox SET created_at = created_at - interval '3 days' WHERE id = $1`, old.ID); err != nil {
		t.Fatal(err)
	}
	// A recent write whose last call was two days ago.
	fresh := x.post("manu", "fresh", itemPath(8, "/close"), ``)
	x.run()
	if _, err := x.conn.Exec(x.ctx, `UPDATE forge_write_audit SET at = at - interval '2 days' WHERE outbox_id = $1`, fresh.ID); err != nil {
		t.Fatal(err)
	}
	ids := map[int64]bool{}
	for _, w := range x.shown() {
		ids[w.ID] = true
	}
	if !ids[old.ID] || ids[fresh.ID] {
		t.Fatalf("the queue shows %v: want the write that failed an instant ago (queued 3 days ago) and not the one whose last call was 2 days ago (queued just now)", ids)
	}
	// And a day on, the first leaves too.
	x.clock.Advance(25 * time.Hour)
	if w := x.shown(); len(w) != 0 {
		t.Fatalf("a failure older than a day is still shown: %+v", w)
	}
}

func TestAServerErrorLeavesTheWritePendingInTheQueueUntilTheForgeAnswers(t *testing.T) {
	x := newRoutes(t)
	n := x.forge.seed("a")
	x.known(n)
	var calls int
	x.forge.set(func(f *fakeForge) {
		f.fail = func(method, path string) int {
			calls++
			if calls == 1 {
				return http.StatusBadGateway
			}
			return 0
		}
	})
	got := x.post("manu", "k1", itemPath(n, "/labels"), `{"label":"priority:high"}`)
	x.run()
	if w := x.shown(); len(w) != 1 || w[0].Status != "pending" || w[0].ID != got.ID {
		t.Fatalf("after a 502 the queue shows %+v, want the write still pending", w)
	}
	if replay := x.post("manu", "k1", itemPath(n, "/labels"), `{"label":"priority:high"}`); replay.Code != http.StatusAccepted || replay.Status != "pending" {
		t.Fatalf("a replay while it retries: %+v", replay)
	}
	if x.run() != 0 {
		t.Fatal("the write was retried before its backoff")
	}
	x.clock.Advance(forge.Backoff(1))
	x.run()
	if w := x.shown(); len(w) != 0 {
		t.Fatalf("an applied write is still shown: %+v", w)
	}
	if _, labels, _ := x.item(n); !hasLabel(labels, "priority:high") {
		t.Fatalf("labels %v, want priority:high applied to the read model", labels)
	}
	if replay := x.post("manu", "k1", itemPath(n, "/labels"), `{"label":"priority:high"}`); replay.Code != http.StatusOK || replay.Status != "applied" {
		t.Fatalf("the replay after it applied: %+v", replay)
	}
}

// The crash the design exists for: the forge made the issue and the process ended before it could
// record that. The client retries with its key, sees it pending, and in the end gets the issue the
// forge made, with no duplicate.
func TestACrashAfterTheForgeMadeTheIssueIsResolvedByItsMarkerWithNoDuplicate(t *testing.T) {
	x := newRoutes(t)
	first := x.post("manu", "k1", createPath, createBody)
	dying := *x.worker
	dying.Store = diesBeforeTheCommit{x.model}
	if _, err := dying.Once(x.ctx); err != nil {
		t.Fatal(err)
	}
	if x.forge.issueCount() != 1 {
		t.Fatalf("setup: the forge holds %d issues, want the one made before the crash", x.forge.issueCount())
	}
	if w := x.shown(); len(w) != 1 || w[0].Status != "pending" {
		t.Fatalf("an in-flight write is shown %+v, want pending", w)
	}
	if replay := x.post("manu", "k1", createPath, createBody); replay.Code != http.StatusAccepted || replay.ID != first.ID {
		t.Fatalf("the client's retry after the crash: %+v", replay)
	}
	if x.run() != 0 {
		t.Fatal("the restarted worker looked before the settle interval passed")
	}
	x.clock.Advance(testHold)
	if x.run() != 1 {
		t.Fatal("the restarted worker did not resume the row")
	}
	if x.forge.issueCount() != 1 || x.forge.count("POST") != 1 {
		t.Fatalf("the forge holds %d issues after %d creates, want exactly one", x.forge.issueCount(), x.forge.count("POST"))
	}
	done := x.post("manu", "k1", createPath, createBody)
	if done.Code != http.StatusOK || done.Status != "applied" || !strings.Contains(done.Response, `"number":1`) {
		t.Fatalf("the retry once resolved: %+v, want the issue the forge made", done)
	}
}

func TestAPullRequestIsNotClosedThroughAnIssueRoute(t *testing.T) {
	x := newRoutes(t)
	pull, issue := x.forge.seed("a pull"), x.forge.seed("an issue")
	x.known(issue)
	x.known(pull)
	if _, err := x.conn.Exec(x.ctx, `UPDATE forge_item SET kind = 'pull' WHERE number = $1`, pull); err != nil {
		t.Fatal(err)
	}
	if got := x.post("manu", "k1", itemPath(pull, "/close"), ``); got.Code != http.StatusUnprocessableEntity {
		t.Fatalf("a close of a pull request: %d %s, want 422", got.Code, got.Raw)
	}
	if got := x.post("manu", "k2", itemPath(issue, "/close"), ``); got.Code != http.StatusAccepted {
		t.Fatalf("a close of an issue: %d %s", got.Code, got.Raw)
	}
	if x.outboxRows() != 1 {
		t.Fatalf("%d rows, want the issue's close only", x.outboxRows())
	}
}

func TestTheMachineAndAnOperatorNeverShareAKeyOrAReceipt(t *testing.T) {
	x := newRoutes(t)
	machine := x.call(x.r, "", "same-key", "POST", "/api/forge/issues", createBody)
	operator := x.post("manu", "same-key", createPath, createBody)
	if machine.Code != http.StatusAccepted || operator.Code != http.StatusAccepted || machine.ID == operator.ID {
		t.Fatalf("one key, two actors: machine %+v, operator %+v, want two rows", machine, operator)
	}
	var actors []string
	rows, err := x.conn.Query(x.ctx, `SELECT actor FROM forge_outbox ORDER BY id`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var a string
		if err := rows.Scan(&a); err != nil {
			t.Fatal(err)
		}
		actors = append(actors, a)
	}
	if strings.Join(actors, ",") != "machine,manu" {
		t.Fatalf("actors %v", actors)
	}
	// An operator cannot take the machine's name to read its receipts.
	if got := x.post("machine", "same-key", createPath, createBody); got.Code != http.StatusForbidden {
		t.Fatalf("Remote-User machine: %d, want 403", got.Code)
	}
}
