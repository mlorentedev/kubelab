package store_test

import (
	"context"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
)

// forgeStub is a forge that holds its items and records what it was asked for.
type forgeStub struct {
	items  []forge.Item
	asked  []time.Time
	answer func(since time.Time) []forge.Item
}

func (f *forgeStub) ListItems(_ context.Context, _ forge.Source, since time.Time) ([]forge.Item, error) {
	f.asked = append(f.asked, since)
	return f.answer(since), nil
}

// CONSOLE-004 AC7: the read model is a cache. With every forge table emptied, the
// next reconcile asks each forge for everything and the queue comes back the same,
// so losing the tables costs one full read and nothing else.
func TestReadModelRebuildsFromTheForgesAlone(t *testing.T) {
	conf := testPostgres(t)
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	empty := func() {
		t.Helper()
		if _, err := conn.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
			t.Fatal(err)
		}
	}
	empty()

	gh := forge.Source{Forge: "github", Owner: "o", Repo: "r"}
	gt := forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}
	t0 := time.Date(2026, 11, 6, 8, 0, 0, 0, time.UTC)
	item := func(n int, state string) forge.Item {
		return forge.Item{Number: n, Kind: forge.KindIssue, Title: "t", State: state, Author: "a",
			Assignees: []string{"x"}, Labels: []string{"l"}, URL: "u", UpdatedAt: t0.Add(time.Duration(n) * time.Minute)}
	}
	// A forge answers everything for the zero time and nothing newer otherwise,
	// the way an incremental read finds no change.
	all := func(items ...forge.Item) *forgeStub {
		f := &forgeStub{items: items}
		f.answer = func(since time.Time) []forge.Item {
			if since.IsZero() {
				return f.items
			}
			return nil
		}
		return f
	}
	hub, tea := all(item(1, "open"), item(2, "open"), item(3, "closed")), all(item(4, "open"))
	model := store.ForgeModel{Conf: conf}
	r := forge.Reconciler{Readers: map[string]forge.Reader{"github": hub, "gitea": tea},
		Catalog: &forge.Catalog{Declared: []forge.Source{gh, gt}}, Model: model, Now: func() time.Time { return t0.Add(time.Hour) }}
	queue := func() forge.QueuePage {
		t.Helper()
		page, err := model.Queue(ctx, []forge.Source{gh, gt}, nil, 500)
		if err != nil {
			t.Fatal(err)
		}
		return page
	}

	if failed := r.Once(ctx); len(failed) != 0 {
		t.Fatalf("first read failed: %v", failed)
	}
	before := queue()
	if before.Total != 3 {
		t.Fatalf("before = %+v, want the 3 open items", before)
	}

	empty()
	if failed := r.Once(ctx); len(failed) != 0 {
		t.Fatalf("rebuild read failed: %v", failed)
	}
	for _, f := range []*forgeStub{hub, tea} {
		if last := f.asked[len(f.asked)-1]; !last.IsZero() {
			t.Fatalf("rebuild asked since %v, want a full read", last)
		}
	}
	if after := queue(); !reflect.DeepEqual(after, before) {
		t.Fatalf("rebuilt queue differs:\n got %+v\nwant %+v", after, before)
	}
}
