package console

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The write routes as a client meets them: the status each refusal gets, what reaches the outbox
// and what never does. The store is a fake that records what it was handed, so "nothing was
// enqueued" is read from the fake and not assumed.

type fakeOutbox struct {
	got     []forge.Enqueue
	receipt forge.Receipt
	err     error
}

func (f *fakeOutbox) Enqueue(_ context.Context, e forge.Enqueue) (forge.Receipt, error) {
	f.got = append(f.got, e)
	if f.err != nil {
		return forge.Receipt{}, f.err
	}
	r := f.receipt
	if r.ID == 0 {
		r = forge.Receipt{ID: int64(len(f.got)), Status: forge.StatusPending}
	}
	return r, nil
}

type fakeKinds map[int]forge.Kind

func (k fakeKinds) ItemKind(_ context.Context, _ forge.Source, n int) (forge.Kind, bool, error) {
	kind, ok := k[n]
	return kind, ok, nil
}

type stubWriter struct{ forge.Writer }

type fakeWrites struct {
	rows  []forge.WriteRow
	err   error
	since time.Time
}

func (f *fakeWrites) Writes(_ context.Context, since time.Time) ([]forge.WriteRow, error) {
	f.since = since
	return f.rows, f.err
}

const repo = "gitea:personal/resume"

// writeRig is the console's engine with a real Intake over fakes. Writers is the gate: a forge
// with a writer takes writes.
type writeRig struct {
	r      *gin.Engine
	outbox *fakeOutbox
	reader *fakeWrites
	now    time.Time
}

func newRig(t *testing.T, writers map[string]forge.Writer) *writeRig {
	t.Helper()
	gin.SetMode(gin.TestMode)
	rig := &writeRig{r: gin.New(), outbox: &fakeOutbox{}, reader: &fakeWrites{}, now: time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)}
	declared, err := forge.ParseSources("gitea:personal/resume,gitea:personal/knowledge,github:mlorentedev/kubelab")
	if err != nil {
		t.Fatal(err)
	}
	w := &Writes{
		Intake: &forge.Intake{
			Store: rig.outbox, Kinds: fakeKinds{7: forge.KindPull, 8: forge.KindIssue}, Writers: writers,
			Sources: func() ([]forge.Source, error) { return declared, nil },
		},
		Reader: rig.reader, Now: func() time.Time { return rig.now },
	}
	Register(rig.r, func() (QueueReader, []forge.Source, error) { return &fakeQueue{}, declared, nil },
		func() string { return consoleHost }, nil, w)
	rig.r.POST("/machine", w.Machine())
	return rig
}

func openWriters() map[string]forge.Writer {
	return map[string]forge.Writer{"gitea": stubWriter{}, "github": stubWriter{}}
}

func (g *writeRig) do(method, path, body string, header map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Host = consoleHost
	req.Header.Set("Remote-User", "operator")
	req.Header.Set("Idempotency-Key", "k-1")
	for k, v := range header {
		if v == "" {
			req.Header.Del(k)
		} else {
			req.Header.Set(k, v)
		}
	}
	w := httptest.NewRecorder()
	g.r.ServeHTTP(w, req)
	return w
}

type call struct {
	name, method, path, body string
	action                   forge.Action
}

// every is one valid request per write route.
var every = []call{
	{"create", "POST", "/console/issues", `{"source":"` + repo + `","title":"Renew the certificate","body":"before Friday"}`, forge.ActionCreate},
	{"add label", "POST", "/console/issues/gitea/personal/resume/8/labels", `{"label":"status:in-progress"}`, forge.ActionAddLabel},
	{"remove label", "DELETE", "/console/issues/gitea/personal/resume/8/labels/priority:high", ``, forge.ActionRemoveLabel},
	{"add assignee", "POST", "/console/issues/gitea/personal/resume/8/assignees", `{"login":"manu"}`, forge.ActionAddAssignee},
	{"remove assignee", "DELETE", "/console/issues/gitea/personal/resume/8/assignees/manu", ``, forge.ActionRemoveAssignee},
	{"close", "POST", "/console/issues/gitea/personal/resume/8/close", ``, forge.ActionClose},
	{"reopen", "POST", "/console/issues/gitea/personal/resume/8/reopen", ``, forge.ActionReopen},
}

func decode[T any](t *testing.T, w *httptest.ResponseRecorder) T {
	t.Helper()
	var v T
	if err := json.Unmarshal(w.Body.Bytes(), &v); err != nil {
		t.Fatalf("answer %q is not the receipt: %v", w.Body.String(), err)
	}
	return v
}

func TestEveryWriteRouteEnqueuesOneRowAndAnswers202Pending(t *testing.T) {
	g := newRig(t, openWriters())
	for i, c := range every {
		w := g.do(c.method, c.path, c.body, nil)
		if w.Code != http.StatusAccepted {
			t.Fatalf("%s: got %d %s, want 202", c.name, w.Code, w.Body)
		}
		got := decode[writeResponse](t, w)
		if got.Status != "pending" || got.ID != int64(i+1) || got.Response != nil && string(got.Response) != "null" || got.Error != nil {
			t.Fatalf("%s: receipt %+v", c.name, got)
		}
		if len(g.outbox.got) != i+1 {
			t.Fatalf("%s: %d rows enqueued, want %d", c.name, len(g.outbox.got), i+1)
		}
		e := g.outbox.got[i]
		if e.Action != c.action || e.Actor != "operator" || e.Key != "k-1" || e.Hash == "" {
			t.Fatalf("%s: enqueued %+v", c.name, e)
		}
	}
	// What each action carried.
	e := g.outbox.got
	if e[0].Payload.Title != "Renew the certificate" || e[0].Payload.Body != "before Friday" || e[0].Number != 0 {
		t.Fatalf("create payload %+v", e[0])
	}
	if e[1].Payload.Label != "status:in-progress" || e[2].Payload.Label != "priority:high" || e[3].Payload.Login != "manu" || e[4].Payload.Login != "manu" {
		t.Fatalf("label and assignee payloads: %+v", e[1:5])
	}
	for _, row := range e[1:] {
		if row.Number != 8 || row.Source.String() != repo {
			t.Fatalf("target of %s: %s #%d", row.Action, row.Source, row.Number)
		}
	}
}

func TestEveryWriteRouteRequiresAnIdempotencyKey(t *testing.T) {
	g := newRig(t, openWriters())
	for _, c := range every {
		for _, key := range []string{"", "   ", "has space", strings.Repeat("k", 256), "naïve"} {
			// A header the client sent empty is the missing one; the others are unusable.
			hdr := map[string]string{"Idempotency-Key": key}
			if key == "" {
				hdr["Idempotency-Key"] = ""
			}
			if w := g.do(c.method, c.path, c.body, hdr); w.Code != http.StatusBadRequest {
				t.Errorf("%s with key %q: got %d, want 400", c.name, key, w.Code)
			}
		}
	}
	if len(g.outbox.got) != 0 {
		t.Fatalf("a request with no usable key enqueued %d rows", len(g.outbox.got))
	}
}

// W14: with the gate off the environment has no writer, so every route answers 503 and nothing is
// enqueued, whatever the request says: a valid one, an invalid one or a replay.
func TestWithNoWriterEveryWriteRouteAnswers503AndEnqueuesNothing(t *testing.T) {
	for name, writers := range map[string]map[string]forge.Writer{"gate off": {}, "nil": nil} {
		g := newRig(t, writers)
		for _, c := range every {
			for _, key := range []string{"k-1", ""} {
				if w := g.do(c.method, c.path, c.body, map[string]string{"Idempotency-Key": key}); w.Code != http.StatusServiceUnavailable {
					t.Errorf("%s, %s, key %q: got %d, want 503", name, c.name, key, w.Code)
				}
			}
		}
		if w := g.do("POST", "/machine", every[0].body, nil); w.Code != http.StatusServiceUnavailable {
			t.Errorf("%s: the machine create answered %d, want 503", name, w.Code)
		}
		if len(g.outbox.got) != 0 {
			t.Fatalf("%s: %d rows enqueued with no writer", name, len(g.outbox.got))
		}
	}
}

func TestAForgeWithNoWriterAnswers503WhileAnotherTakesWrites(t *testing.T) {
	g := newRig(t, map[string]forge.Writer{"github": stubWriter{}})
	if w := g.do("POST", every[0].path, every[0].body, nil); w.Code != http.StatusServiceUnavailable {
		t.Fatalf("a Gitea create with only a GitHub writer: %d, want 503", w.Code)
	}
	gh := `{"source":"github:mlorentedev/kubelab","title":"t"}`
	if w := g.do("POST", every[0].path, gh, nil); w.Code != http.StatusAccepted {
		t.Fatalf("a GitHub create: %d %s, want 202", w.Code, w.Body)
	}
	if len(g.outbox.got) != 1 {
		t.Fatalf("%d rows enqueued, want the GitHub one only", len(g.outbox.got))
	}
}

func TestAReplayReturnsTheStoredReceipt(t *testing.T) {
	g := newRig(t, openWriters())
	applied := json.RawMessage(`{"number":12,"url":"https://forge/o/r/issues/12"}`)
	cases := []struct {
		name    string
		receipt forge.Receipt
		code    int
		status  string
	}{
		{"still pending", forge.Receipt{ID: 5, Status: forge.StatusPending, Replay: true}, 202, "pending"},
		{"in flight is shown pending", forge.Receipt{ID: 5, Status: forge.StatusInFlight, Replay: true}, 202, "pending"},
		{"applied", forge.Receipt{ID: 5, Status: forge.StatusApplied, Replay: true, Response: applied}, 200, "applied"},
		{"failed", forge.Receipt{ID: 5, Status: forge.StatusFailed, Replay: true, LastError: "forge answered 422"}, 200, "failed"},
	}
	for _, c := range cases {
		g.outbox.receipt = c.receipt
		w := g.do("POST", every[0].path, every[0].body, nil)
		if w.Code != c.code {
			t.Fatalf("%s: got %d, want %d", c.name, w.Code, c.code)
		}
		got := decode[writeResponse](t, w)
		if got.ID != 5 || got.Status != c.status {
			t.Fatalf("%s: receipt %+v", c.name, got)
		}
		if c.status == "applied" && string(got.Response) != string(applied) {
			t.Fatalf("%s: response %s, want the stored one", c.name, got.Response)
		}
		if c.status == "failed" && (got.Error == nil || *got.Error != "forge answered 422") {
			t.Fatalf("%s: error %v", c.name, got.Error)
		}
	}
}

func TestTheSameKeyWithAnotherRequestIs422(t *testing.T) {
	g := newRig(t, openWriters())
	g.outbox.err = forge.ErrKeyReuse
	w := g.do("POST", every[0].path, every[0].body, nil)
	if w.Code != http.StatusUnprocessableEntity {
		t.Fatalf("got %d %s, want 422", w.Code, w.Body)
	}
}

// The hash covers the action, the target and every field, so one key reused on another issue, on
// another repository, for another action or with another body is another request.
func TestTheRequestHashCoversTheActionTheTargetAndTheBody(t *testing.T) {
	base := forge.Request{Actor: "operator", Action: forge.ActionAddLabel, Number: 8, Label: "status:blocked",
		Source: forge.Source{Forge: "gitea", Owner: "personal", Repo: "resume"}}
	same := base
	same.Source = forge.Source{Forge: "GITEA", Owner: "Personal", Repo: "RESUME"}
	if forge.HashOf(base) != forge.HashOf(same) {
		t.Fatal("a target spelled in another case is the same request")
	}
	vary := map[string]func(r *forge.Request){
		"issue":      func(r *forge.Request) { r.Number = 9 },
		"repository": func(r *forge.Request) { r.Source.Repo = "knowledge" },
		"owner":      func(r *forge.Request) { r.Source.Owner = "teledyne" },
		"forge":      func(r *forge.Request) { r.Source.Forge = "github" },
		"action":     func(r *forge.Request) { r.Action = forge.ActionRemoveLabel },
		"label":      func(r *forge.Request) { r.Label = "status:done" },
		"login":      func(r *forge.Request) { r.Login = "manu" },
		"title":      func(r *forge.Request) { r.Title = "t" },
		"body":       func(r *forge.Request) { r.Body = "b" },
	}
	for name, mutate := range vary {
		other := base
		mutate(&other)
		if forge.HashOf(base) == forge.HashOf(other) {
			t.Errorf("a request on another %s hashes like the original: one key could replay it", name)
		}
	}
}

func TestATargetOutsideTheDeclaredSourcesIs422AndEnqueuesNothing(t *testing.T) {
	g := newRig(t, openWriters())
	outside := []call{
		{"create elsewhere", "POST", "/console/issues", `{"source":"gitea:personal/secret","title":"t"}`, forge.ActionCreate},
		{"another owner", "POST", "/console/issues", `{"source":"gitea:other/resume","title":"t"}`, forge.ActionCreate},
		{"label elsewhere", "POST", "/console/issues/gitea/personal/secret/8/labels", `{"label":"status:done"}`, forge.ActionAddLabel},
		{"close elsewhere", "POST", "/console/issues/github/someone/else/8/close", ``, forge.ActionClose},
	}
	for _, c := range outside {
		if w := g.do(c.method, c.path, c.body, nil); w.Code != http.StatusUnprocessableEntity {
			t.Errorf("%s: got %d %s, want 422", c.name, w.Code, w.Body)
		}
	}
	if len(g.outbox.got) != 0 {
		t.Fatalf("%d rows enqueued for targets outside infra.forge.sources", len(g.outbox.got))
	}
	// The declaration's own spelling is what is stored, however the request wrote it.
	if w := g.do("POST", every[0].path, `{"source":"gitea:PERSONAL/Resume","title":"t"}`, nil); w.Code != http.StatusAccepted {
		t.Fatalf("a declared source in another case: %d %s", w.Code, w.Body)
	}
	if got := g.outbox.got[0].Source.String(); got != repo {
		t.Fatalf("stored %s, want the declared spelling %s", got, repo)
	}
}

func TestADeclarationThatCannotBeReadIs503(t *testing.T) {
	g := newRig(t, openWriters())
	g.r = gin.New()
	w := &Writes{Intake: &forge.Intake{Store: g.outbox, Kinds: fakeKinds{}, Writers: openWriters(),
		Sources: func() ([]forge.Source, error) { return nil, errors.New("no catalog") }}}
	Register(g.r, func() (QueueReader, []forge.Source, error) { return &fakeQueue{}, nil, nil }, func() string { return consoleHost }, nil, w)
	if got := g.do("POST", every[0].path, every[0].body, nil); got.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d, want 503, never an empty set that refuses everything as 422", got.Code)
	}
}

func TestWhatThePlatformDoesNotPerformIs422(t *testing.T) {
	g := newRig(t, openWriters())
	cases := []call{
		{"a label outside the workflow", "POST", "/console/issues/gitea/personal/resume/8/labels", `{"label":"area:infra"}`, ""},
		{"a bare prefix", "POST", "/console/issues/gitea/personal/resume/8/labels", `{"label":"status:"}`, ""},
		{"a label removal outside the workflow", "DELETE", "/console/issues/gitea/personal/resume/8/labels/bug", ``, ""},
		{"a close of a pull request", "POST", "/console/issues/gitea/personal/resume/7/close", ``, ""},
		{"a reopen of a pull request", "POST", "/console/issues/gitea/personal/resume/7/reopen", ``, ""},
		{"a title carrying the marker", "POST", "/console/issues", `{"source":"` + repo + `","title":"<!-- kubelab-write:1 -->"}`, ""},
		{"a body carrying the marker", "POST", "/console/issues", `{"source":"` + repo + `","title":"t","body":"x <!-- KUBELAB-WRITE:1 -->"}`, ""},
	}
	for _, c := range cases {
		if w := g.do(c.method, c.path, c.body, nil); w.Code != http.StatusUnprocessableEntity {
			t.Errorf("%s: got %d %s, want 422", c.name, w.Code, w.Body)
		}
	}
	if len(g.outbox.got) != 0 {
		t.Fatalf("%d rows enqueued for refused requests", len(g.outbox.got))
	}
	// An issue the read model has not met is the forge's to judge, and a label on a pull request is fine.
	for _, c := range []call{
		{"close of an unknown number", "POST", "/console/issues/gitea/personal/resume/99/close", ``, ""},
		{"a label on a pull request", "POST", "/console/issues/gitea/personal/resume/7/labels", `{"label":"priority:high"}`, ""},
	} {
		if w := g.do(c.method, c.path, c.body, nil); w.Code != http.StatusAccepted {
			t.Errorf("%s: got %d %s, want 202", c.name, w.Code, w.Body)
		}
	}
}

func TestAMalformedRequestIs400(t *testing.T) {
	g := newRig(t, openWriters())
	cases := []call{
		{"not JSON", "POST", "/console/issues", `nope`, ""},
		{"an empty body", "POST", "/console/issues", ``, ""},
		{"an unknown field", "POST", "/console/issues", `{"source":"` + repo + `","title":"t","labels":["x"]}`, ""},
		{"two values", "POST", "/console/issues", `{"source":"` + repo + `","title":"t"}{}`, ""},
		{"a wildcard source", "POST", "/console/issues", `{"source":"gitea:personal/*","title":"t"}`, ""},
		{"no source", "POST", "/console/issues", `{"title":"t"}`, ""},
		{"an unknown forge", "POST", "/console/issues", `{"source":"gitlab:o/r","title":"t"}`, ""},
		{"no title", "POST", "/console/issues", `{"source":"` + repo + `","title":"  "}`, ""},
		{"a two-line title", "POST", "/console/issues", `{"source":"` + repo + `","title":"a\nb"}`, ""},
		{"a title over the bound", "POST", "/console/issues", `{"source":"` + repo + `","title":"` + strings.Repeat("t", 257) + `"}`, ""},
		{"a body over the bound", "POST", "/console/issues", `{"source":"` + repo + `","title":"t","body":"` + strings.Repeat("b", 60001) + `"}`, ""},
		{"a body past the request bound", "POST", "/console/issues", `{"source":"` + repo + `","title":"t","body":"` + strings.Repeat("b", 200000) + `"}`, ""},
		{"a number that is not one", "POST", "/console/issues/gitea/personal/resume/x/close", ``, ""},
		{"number zero", "POST", "/console/issues/gitea/personal/resume/0/close", ``, ""},
		{"a negative number", "POST", "/console/issues/gitea/personal/resume/-3/close", ``, ""},
		{"an unknown forge in the path", "POST", "/console/issues/gitlab/personal/resume/8/close", ``, ""},
		{"a label with no body", "POST", "/console/issues/gitea/personal/resume/8/labels", ``, ""},
		{"an empty label", "POST", "/console/issues/gitea/personal/resume/8/labels", `{"label":""}`, ""},
		{"a login with a slash", "POST", "/console/issues/gitea/personal/resume/8/assignees", `{"login":"a/b"}`, ""},
		{"an unknown field on a label", "POST", "/console/issues/gitea/personal/resume/8/labels", `{"label":"status:x","extra":1}`, ""},
	}
	for _, c := range cases {
		if w := g.do(c.method, c.path, c.body, nil); w.Code != http.StatusBadRequest {
			t.Errorf("%s: got %d %s, want 400", c.name, w.Code, w.Body)
		}
	}
	if len(g.outbox.got) != 0 {
		t.Fatalf("%d rows enqueued for malformed requests", len(g.outbox.got))
	}
}

func TestADatabaseFailureIs503WithoutItsText(t *testing.T) {
	g := newRig(t, openWriters())
	g.outbox.err = errors.New("pq: password authentication failed for user api")
	w := g.do("POST", every[0].path, every[0].body, nil)
	if w.Code != http.StatusServiceUnavailable || strings.Contains(w.Body.String(), "password") {
		t.Fatalf("got %d %s", w.Code, w.Body)
	}
}

// An actor is half of an idempotency key's scope, so the machine's name must not be claimable
// from the header Authelia sets: an operator named `machine` could otherwise replay the machine's
// keys and be handed its stored responses.
func TestARemoteUserNamedLikeTheMachineIsRefused(t *testing.T) {
	g := newRig(t, openWriters())
	for _, c := range every {
		for _, user := range []string{"machine", "Machine", " MACHINE "} {
			if w := g.do(c.method, c.path, c.body, map[string]string{"Remote-User": user}); w.Code != http.StatusForbidden {
				t.Errorf("%s as %q: got %d, want 403", c.name, user, w.Code)
			}
		}
	}
	if len(g.outbox.got) != 0 {
		t.Fatalf("%d rows enqueued for the machine's name", len(g.outbox.got))
	}
}

func TestTheMachineCreateWritesAsTheMachineWhateverTheRequestSays(t *testing.T) {
	g := newRig(t, openWriters())
	w := g.do("POST", "/machine", every[0].body, map[string]string{"Remote-User": "operator"})
	if w.Code != http.StatusAccepted {
		t.Fatalf("got %d %s", w.Code, w.Body)
	}
	if got := g.outbox.got[0]; got.Actor != forge.MachineActor || got.Action != forge.ActionCreate {
		t.Fatalf("enqueued %+v", got)
	}
	// The same key from the operator is another row's key: the namespaces never meet.
	if w := g.do("POST", every[0].path, every[0].body, nil); w.Code != http.StatusAccepted || g.outbox.got[1].Actor != "operator" {
		t.Fatalf("the operator's create under the machine's key: %d, actor %q", w.Code, g.outbox.got[1].Actor)
	}
}

func queueWrites(t *testing.T, g *writeRig) []writeView {
	t.Helper()
	req := httptest.NewRequest("GET", "/console/queue", nil)
	req.Host = consoleHost
	w := httptest.NewRecorder()
	g.r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("queue: %d", w.Code)
	}
	return decode[queueView](t, w).Writes
}

func TestTheQueueListsWhatIsOwedAndWhatFailed(t *testing.T) {
	g := newRig(t, openWriters())
	if got := queueWrites(t, g); got == nil || len(got) != 0 {
		t.Fatalf("with nothing owed writes is %v, want an empty list and not null", got)
	}
	g.reader.rows = []forge.WriteRow{
		{ID: 1, Action: forge.ActionCreate, Source: forge.Source{Forge: "gitea", Owner: "personal", Repo: "resume"}, Detail: "Renew", Status: "pending", QueuedAt: g.now},
		{ID: 2, Action: forge.ActionAddLabel, Source: forge.Source{Forge: "gitea", Owner: "personal", Repo: "resume"}, Number: 8, Detail: "status:done", Status: "failed", LastError: "forge answered 404", QueuedAt: g.now},
	}
	got := queueWrites(t, g)
	if len(got) != 2 || got[0].Number != nil || got[0].Error != nil || got[0].Source != repo || got[0].Detail != "Renew" {
		t.Fatalf("the pending create: %+v", got)
	}
	if got[1].Number == nil || *got[1].Number != 8 || got[1].Status != "failed" || got[1].Error == nil || *got[1].Error != "forge answered 404" {
		t.Fatalf("the failed label: %+v", got[1])
	}
	// The failed window is the last day, asked of the reader.
	if want := g.now.Add(-24 * time.Hour); !g.reader.since.Equal(want) {
		t.Fatalf("the reader was asked for failures since %s, want %s", g.reader.since, want)
	}
}

func TestTheQueueIs503WhenTheOutboxCannotBeRead(t *testing.T) {
	g := newRig(t, openWriters())
	g.reader.err = errors.New("db down")
	req := httptest.NewRequest("GET", "/console/queue", nil)
	req.Host = consoleHost
	w := httptest.NewRecorder()
	g.r.ServeHTTP(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d: a queue that left out what is owed would read as nothing pending", w.Code)
	}
}
