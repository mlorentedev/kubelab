package forge_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

const issuePayload = `{"action":"opened","repository":{"name":"r","owner":{"login":"o"}},
"issue":{"number":7,"title":"t","state":"open","html_url":"u","updated_at":"2026-11-02T08:00:00Z",
"user":{"login":"a"},"labels":[{"name":"status:ready"}]}}`

const pullPayload = `{"repository":{"name":"r","owner":{"login":"o"}},
"pull_request":{"number":8,"title":"p","state":"open","html_url":"u","updated_at":"2026-11-02T08:00:00Z",
"user":{"login":"a"}}}`

func TestItemFromEvent(t *testing.T) {
	item, err := forge.ItemFromEvent(forge.Event{Forge: "gitea", Type: "issues", Payload: []byte(issuePayload)})
	if err != nil || item == nil {
		t.Fatalf("%v, %v", item, err)
	}
	want := forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}
	if item.Source != want || item.Number != 7 || item.Kind != forge.KindIssue || len(item.Labels) != 1 {
		t.Fatalf("item = %+v", item)
	}
	pull, err := forge.ItemFromEvent(forge.Event{Forge: "github", Type: "pull_request", Payload: []byte(pullPayload)})
	if err != nil || pull == nil || pull.Kind != forge.KindPull {
		t.Fatalf("%+v, %v", pull, err)
	}
	other, err := forge.ItemFromEvent(forge.Event{Forge: "github", Type: "ping", Payload: []byte(`{"zen":"x"}`)})
	if err != nil || other != nil {
		t.Fatalf("%+v, %v", other, err)
	}
}

type fakeLog struct {
	pending   []forge.Event
	projected map[string]*forge.Item
	refuse    int
}

func (f *fakeLog) Pending(context.Context, int) ([]forge.Event, error) { return f.pending, nil }

func (f *fakeLog) Project(_ context.Context, e forge.Event, item *forge.Item) error {
	if item != nil && item.Number == f.refuse {
		return errors.New("refused")
	}
	f.projected[e.DeliveryID] = item
	f.pending = nil
	return nil
}

func TestProjectorMarksEvenWhatItCannotRead(t *testing.T) {
	l := &fakeLog{projected: map[string]*forge.Item{}, pending: []forge.Event{
		{Forge: "gitea", DeliveryID: "ok", Type: "issues", Payload: []byte(issuePayload)},
		{Forge: "gitea", DeliveryID: "bad", Type: "issues", Payload: []byte(`[]`)},
	}}
	p := forge.Projector{Log: l}
	if err := p.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if l.projected["ok"] == nil {
		t.Fatal("readable delivery not projected")
	}
	if item, seen := l.projected["bad"]; !seen || item != nil {
		t.Fatalf("unreadable delivery: seen=%v item=%v", seen, item)
	}
}

func TestDeletedItemIsNotWrittenBack(t *testing.T) {
	payload := strings.Replace(issuePayload, `"opened"`, `"deleted"`, 1)
	item, err := forge.ItemFromEvent(forge.Event{Forge: "github", Type: "issues", Payload: []byte(payload)})
	if err != nil || item != nil {
		t.Fatalf("%+v, %v", item, err)
	}
}

func TestRefusedDeliveryIsMarkedSoItCannotStarveTheBatch(t *testing.T) {
	l := &fakeLog{projected: map[string]*forge.Item{}, refuse: 7, pending: []forge.Event{
		{Forge: "gitea", DeliveryID: "poison", Type: "issues", Payload: []byte(issuePayload)},
	}}
	p := forge.Projector{Log: l}
	if err := p.Once(context.Background()); err != nil {
		t.Fatal(err)
	}
	if item, seen := l.projected["poison"]; !seen || item != nil {
		t.Fatalf("seen=%v item=%v", seen, item)
	}
}
