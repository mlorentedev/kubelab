package store_test

import (
	"context"
	"os"
	"strconv"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// Runs against a real database when FORGE_TEST_POSTGRES_PORT names a local one with the
// migrations applied, because the guarantee lives in the SQL and not in the Go around it.
func TestStoreEventTwiceKeepsOneRow(t *testing.T) {
	port := os.Getenv("FORGE_TEST_POSTGRES_PORT")
	if port == "" {
		t.Skip("FORGE_TEST_POSTGRES_PORT is not set")
	}
	if _, err := strconv.Atoi(port); err != nil {
		t.Fatal(err)
	}
	conf := config.Postgres{Host: "127.0.0.1", Port: port, Tenant: "api", Password: "fixture"}
	ctx := context.Background()
	for i := 0; i < 2; i++ {
		if err := store.StoreEvent(ctx, conf, "gitea", "d1", "issues", []byte(`{"a":1}`)); err != nil {
			t.Fatal(err)
		}
	}
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	var rows int
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM forge_event WHERE payload->>'a' = '1'`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != 1 {
		t.Fatalf("rows = %d, want 1", rows)
	}
}

func TestReadModelRoundTrip(t *testing.T) {
	port := os.Getenv("FORGE_TEST_POSTGRES_PORT")
	if port == "" {
		t.Skip("FORGE_TEST_POSTGRES_PORT is not set")
	}
	conf := config.Postgres{Host: "127.0.0.1", Port: port, Tenant: "api", Password: "fixture"}
	ctx := context.Background()
	model := store.ForgeModel{Conf: conf}
	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}

	if got, err := model.LastRead(ctx, src); err != nil || !got.IsZero() {
		t.Fatalf("unread source: %v, %v", got, err)
	}
	now := time.Date(2026, 11, 2, 8, 0, 0, 0, time.UTC)
	item := forge.Item{Number: 1, Kind: forge.KindIssue, Title: "t", State: "open", Author: "a", URL: "u", UpdatedAt: now}
	for i := 0; i < 2; i++ {
		if err := model.SaveRead(ctx, src, []forge.Item{item}, now); err != nil {
			t.Fatal(err)
		}
	}
	if err := model.MarkUnreachable(ctx, src, now.Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	got, err := model.LastRead(ctx, src)
	if err != nil || !got.Equal(now) {
		t.Fatalf("as_of after a failure = %v, %v", got, err)
	}
}

func TestSameDeliveryProjectsOnce(t *testing.T) {
	port := os.Getenv("FORGE_TEST_POSTGRES_PORT")
	if port == "" {
		t.Skip("FORGE_TEST_POSTGRES_PORT is not set")
	}
	conf := config.Postgres{Host: "127.0.0.1", Port: port, Tenant: "api", Password: "fixture"}
	ctx := context.Background()
	model := store.ForgeModel{Conf: conf}
	cleanup, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup.Close(ctx)
	if _, err := cleanup.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
		t.Fatal(err)
	}
	payload := []byte(`{"repository":{"name":"p","owner":{"login":"o"}},"issue":{"number":3,"title":"new","state":"open",
		"html_url":"u","updated_at":"2026-11-02T09:00:00Z","user":{"login":"a"}}}`)
	stale := []byte(`{"repository":{"name":"p","owner":{"login":"o"}},"issue":{"number":3,"title":"old","state":"open",
		"html_url":"u","updated_at":"2026-11-02T08:00:00Z","user":{"login":"a"}}}`)
	if err := store.StoreEvent(ctx, conf, "gitea", "new", "issues", payload); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreEvent(ctx, conf, "gitea", "new", "issues", payload); err != nil {
		t.Fatal(err)
	}
	projector := forge.Projector{Log: model}
	if err := projector.Once(ctx); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreEvent(ctx, conf, "gitea", "old", "issues", stale); err != nil {
		t.Fatal(err)
	}
	if err := projector.Once(ctx); err != nil {
		t.Fatal(err)
	}
	if left, err := model.Pending(ctx, 10); err != nil || len(left) != 0 {
		t.Fatalf("pending = %v, %v", left, err)
	}
	var title string
	var rows int
	err = cleanup.QueryRow(ctx, `SELECT max(title), count(*) FROM forge_item WHERE repo = 'p'`).Scan(&title, &rows)
	if err != nil || rows != 1 || title != "new" {
		t.Fatalf("title = %q, rows = %d, err = %v", title, rows, err)
	}
}

func TestQueueReadsDeclaredOpenItemsNewestFirst(t *testing.T) {
	port := os.Getenv("FORGE_TEST_POSTGRES_PORT")
	if port == "" {
		t.Skip("FORGE_TEST_POSTGRES_PORT is not set")
	}
	conf := config.Postgres{Host: "127.0.0.1", Port: port, Tenant: "api", Password: "fixture"}
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
		t.Fatal(err)
	}
	model := store.ForgeModel{Conf: conf}
	read := forge.Source{Forge: "github", Owner: "o", Repo: "read"}
	gone := forge.Source{Forge: "github", Owner: "o", Repo: "undeclared"}
	never := forge.Source{Forge: "gitea", Owner: "o", Repo: "never"}
	t0 := time.Date(2026, 11, 3, 8, 0, 0, 0, time.UTC)
	item := func(n int, state string, at time.Time) forge.Item {
		return forge.Item{Number: n, Kind: forge.KindIssue, Title: "t", State: state, Author: "a", URL: "u", UpdatedAt: at}
	}
	if err := model.SaveRead(ctx, read, []forge.Item{item(1, "open", t0), item(2, "open", t0.Add(time.Hour)),
		item(3, "closed", t0.Add(2*time.Hour))}, t0); err != nil {
		t.Fatal(err)
	}
	if err := model.SaveRead(ctx, gone, []forge.Item{item(9, "open", t0)}, t0); err != nil {
		t.Fatal(err)
	}

	states, items, err := model.Queue(ctx, []forge.Source{read, never})
	if err != nil {
		t.Fatal(err)
	}
	if len(states) != 2 || states[0].Source != read || !states[0].Reachable || states[0].AsOf == nil ||
		states[1].Source != never || states[1].Reachable || states[1].AsOf != nil {
		t.Fatalf("states = %+v", states)
	}
	if len(items) != 2 || items[0].Number != 2 || items[1].Number != 1 || items[0].Source != read {
		t.Fatalf("items = %+v, want open items 2 then 1 of the declared source", items)
	}
}
