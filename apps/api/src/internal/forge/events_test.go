package forge_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// events captures the structured lines a component writes, one JSON object each.
type events struct{ buf bytes.Buffer }

func (e *events) logger() *slog.Logger { return slog.New(slog.NewJSONHandler(&e.buf, nil)) }

func (e *events) named(t *testing.T, name string) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(e.buf.String()), "\n") {
		if line == "" {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("not one JSON object per line: %q: %v", line, err)
		}
		if m["event"] == name {
			out = append(out, m)
		}
	}
	return out
}

func TestReconcileWritesFreshnessPerSourceAndOneCycleEvent(t *testing.T) {
	up := forge.Source{Forge: "github", Owner: "o", Repo: "up"}
	down := forge.Source{Forge: "gitea", Owner: "o", Repo: "down"}
	model := newModel()
	last := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	model.lastRead[down.String()] = last
	now := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	var ev events
	r := forge.Reconciler{
		Readers: map[string]forge.Reader{"github": &fakeReader{}, "gitea": &fakeReader{err: errors.New("down")}},
		Catalog: &forge.Catalog{Declared: []forge.Source{down, up}},
		Model:   model,
		Now:     func() time.Time { return now },
		Events:  ev.logger(),
	}
	r.Once(context.Background())

	fresh := map[string]map[string]any{}
	for _, e := range ev.named(t, forge.EventSourceFreshness) {
		fresh[e["source"].(string)] = e
	}
	if len(fresh) != 2 {
		t.Fatalf("freshness events = %v", fresh)
	}
	if e := fresh[up.String()]; e["reachable"] != true || e["as_of"] != now.Format(time.RFC3339) || e["age_seconds"] != 0.0 {
		t.Fatalf("up = %v", e)
	}
	// A failed read keeps the last as_of, so its age is what an alert reads.
	if e := fresh[down.String()]; e["reachable"] != false || e["as_of"] != last.Format(time.RFC3339) ||
		e["age_seconds"] != 86400.0 || e["error"] == nil || e["level"] != "WARN" {
		t.Fatalf("down = %v", e)
	}
	cycles := ev.named(t, forge.EventReconcileCycle)
	if len(cycles) != 1 {
		t.Fatalf("cycle events = %v", cycles)
	}
	c := cycles[0]
	if c["scope"] != "full" || c["sources"] != 2.0 || c["failed"] != 1.0 {
		t.Fatalf("cycle = %v", c)
	}
	if d, ok := c["duration_ms"].(float64); !ok || d < 0 {
		t.Fatalf("duration_ms = %v", c["duration_ms"])
	}
}

// A source never read has no as_of: the event says so instead of inventing an age.
func TestFreshnessOfASourceNeverReadHasNoAge(t *testing.T) {
	src := forge.Source{Forge: "gitlab", Owner: "o", Repo: "r"}
	var ev events
	r := forge.Reconciler{Catalog: &forge.Catalog{Declared: []forge.Source{src}}, Model: newModel(), Events: ev.logger()}
	r.Once(context.Background())

	got := ev.named(t, forge.EventSourceFreshness)
	if len(got) != 1 || got[0]["reachable"] != false {
		t.Fatalf("freshness = %v", got)
	}
	if _, has := got[0]["as_of"]; has {
		t.Fatalf("as_of on a source never read: %v", got[0])
	}
	if _, has := got[0]["age_seconds"]; has {
		t.Fatalf("age on a source never read: %v", got[0])
	}
}

func TestReceiverWritesOneFailureEventPerRefusal(t *testing.T) {
	const secret, body = "fixture", `{"action":"opened","repository":{"name":"kubelab","owner":{"login":"mlorentedev"}}}`
	signed := header("X-Gitea-Signature", sign(secret, body), "X-Gitea-Delivery", "d9", "X-Gitea-Event", "issues")
	forged := header("X-Gitea-Signature", sign("other", body), "X-Gitea-Delivery", "attacker-chosen", "X-Gitea-Event", "issues")
	cases := []struct {
		name, decl, reason string
		h                  map[string][]string
		store              *fakeStore
		status             int
	}{
		{"signature", "gitea:mlorentedev/kubelab", "signature", forged, &fakeStore{}, 401},
		{"sources", "not-a-source", "sources", signed, &fakeStore{}, 503},
		{"store", "gitea:mlorentedev/kubelab", "store", signed, &fakeStore{err: errors.New("no table")}, 503},
	}
	for _, tc := range cases {
		var ev events
		rc := forge.NewReceiver(tc.decl, map[string]string{"gitea": secret}, tc.store)
		rc.Events = ev.logger()
		if got := rc.Handle(context.Background(), "gitea", tc.h, strings.NewReader(body)); got != tc.status {
			t.Fatalf("%s: status %d, want %d", tc.name, got, tc.status)
		}
		got := ev.named(t, forge.EventWebhookFailure)
		if len(got) != 1 || got[0]["reason"] != tc.reason || got[0]["forge"] != "gitea" || got[0]["status"] != float64(tc.status) {
			t.Fatalf("%s: events = %v", tc.name, got)
		}
		// An unsigned caller chooses its headers; none of them reach the log.
		if _, has := got[0]["delivery"]; has == (tc.reason == "signature") {
			t.Fatalf("%s: delivery field = %v", tc.name, got[0]["delivery"])
		}
	}
}

func TestReceiverWritesNoFailureEventOnSuccess(t *testing.T) {
	const secret, body = "fixture", `{"action":"opened","repository":{"name":"kubelab","owner":{"login":"mlorentedev"}}}`
	var ev events
	rc := forge.NewReceiver("gitea:mlorentedev/kubelab", map[string]string{"gitea": secret}, &fakeStore{})
	rc.Events = ev.logger()
	h := header("X-Gitea-Signature", sign(secret, body), "X-Gitea-Delivery", "d", "X-Gitea-Event", "issues")
	if got := rc.Handle(context.Background(), "gitea", h, strings.NewReader(body)); got != 202 {
		t.Fatalf("status %d", got)
	}
	if got := ev.named(t, forge.EventWebhookFailure); len(got) != 0 {
		t.Fatalf("events = %v", got)
	}
}

func TestProjectorWritesAFailureEventPerDeliveryItCouldNotProject(t *testing.T) {
	var ev events
	l := &fakeLog{projected: map[string]*forge.Item{}, refuse: 7, pending: []forge.Event{
		{Forge: "gitea", DeliveryID: "bad", Type: "issues", Payload: []byte(`[]`)},
		{Forge: "gitea", DeliveryID: "poison", Type: "issues", Payload: []byte(issuePayload)},
	}}
	p := forge.Projector{Log: l, Events: ev.logger()}
	if err := p.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	reasons := map[string]any{}
	for _, e := range ev.named(t, forge.EventWebhookFailure) {
		reasons[e["delivery"].(string)] = e["reason"]
	}
	if reasons["bad"] != "unreadable" || reasons["poison"] != "projection" || len(reasons) != 2 {
		t.Fatalf("reasons = %v", reasons)
	}
}

func TestProjectorWritesTheBacklogIncludingZeroAtMostOncePerPeriod(t *testing.T) {
	var ev events
	now := time.Date(2026, 11, 13, 1, 0, 0, 0, time.UTC)
	l := &fakeLog{projected: map[string]*forge.Item{}, depth: 3, oldest: now.Add(-90 * time.Second)}
	p := forge.Projector{Log: l, Events: ev.logger(), Now: func() time.Time { return now }}

	for _, step := range []time.Duration{0, forge.ProjectPeriod, forge.BacklogPeriod - forge.ProjectPeriod} {
		now = now.Add(step)
		if err := p.Once(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	got := ev.named(t, forge.EventProjectionBacklog)
	if len(got) != 2 || l.backlogs != 2 {
		t.Fatalf("lines = %v, backlog reads = %d: want one per %s", got, l.backlogs, forge.BacklogPeriod)
	}
	if got[0]["depth"] != float64(3) || got[0]["oldest_age_seconds"] != float64(90) {
		t.Fatalf("first line = %v", got[0])
	}

	// An empty queue still writes a line, so silence can only mean a stopped projector.
	l.depth, l.oldest = 0, time.Time{}
	now = now.Add(forge.BacklogPeriod)
	if err := p.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	got = ev.named(t, forge.EventProjectionBacklog)
	if last := got[len(got)-1]; last["depth"] != float64(0) || last["oldest_age_seconds"] != float64(0) {
		t.Fatalf("empty queue line = %v", last)
	}
}

func TestProjectorStillProjectsWhenTheBacklogCannotBeCounted(t *testing.T) {
	var ev events
	l := &fakeLog{projected: map[string]*forge.Item{}, backlogErr: errors.New("count failed"), pending: []forge.Event{
		{Forge: "gitea", DeliveryID: "ok", Type: "issues", Payload: []byte(issuePayload)},
	}}
	p := forge.Projector{Log: l, Events: ev.logger()}
	if err := p.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if l.projected["ok"] == nil {
		t.Fatal("delivery not projected")
	}
	if got := ev.named(t, forge.EventProjectionBacklog); len(got) != 0 {
		t.Fatalf("a failed count wrote %v", got)
	}
}
