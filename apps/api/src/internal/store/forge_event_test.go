package store_test

import (
	"context"
	"errors"
	"os"
	"strconv"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// testPostgres is the database the store tests run against: a local one with the
// migrations applied, named by FORGE_TEST_POSTGRES_PORT, because the guarantee lives
// in the SQL and not in the Go around it. Without one the tests skip, except in CI,
// where a skip would let the job go green with the store untested (#3117).
func testPostgres(t *testing.T) config.Postgres {
	t.Helper()
	port := os.Getenv("FORGE_TEST_POSTGRES_PORT")
	if port == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("FORGE_TEST_POSTGRES_PORT is not set in CI: the store tests would not run")
		}
		t.Skip("FORGE_TEST_POSTGRES_PORT is not set")
	}
	if _, err := strconv.Atoi(port); err != nil {
		t.Fatal(err)
	}
	return config.Postgres{Host: "127.0.0.1", Port: port, Tenant: "api", Password: "fixture"}
}

func TestStoreEventTwiceKeepsOneRow(t *testing.T) {
	conf := testPostgres(t)
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
	conf := testPostgres(t)
	ctx := context.Background()
	model := store.ForgeModel{Conf: conf}
	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}
	// Another test reads the same source; without this the test passes only on a new database.
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
		t.Fatal(err)
	}

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
	conf := testPostgres(t)
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

func TestBacklogCountsEveryPendingDeliveryNotABatch(t *testing.T) {
	conf := testPostgres(t)
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
	if depth, oldest, err := model.Backlog(ctx); err != nil || depth != 0 || !oldest.IsZero() {
		t.Fatalf("empty: depth = %d, oldest = %v, err = %v", depth, oldest, err)
	}
	// More than one Pending batch, so a count taken from Pending would stop at its limit.
	for i := 0; i < 60; i++ {
		if err := store.StoreEvent(ctx, conf, "gitea", "d"+strconv.Itoa(i), "issues", []byte(`{}`)); err != nil {
			t.Fatal(err)
		}
	}
	first := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	if _, err := cleanup.Exec(ctx, `UPDATE forge_event SET received_at = $1 WHERE delivery_id = 'd0'`, first); err != nil {
		t.Fatal(err)
	}
	if _, err := cleanup.Exec(ctx, `UPDATE forge_event SET projected_at = now() WHERE delivery_id = 'd1'`); err != nil {
		t.Fatal(err)
	}
	depth, oldest, err := model.Backlog(ctx)
	if err != nil || depth != 59 || !oldest.Equal(first) {
		t.Fatalf("depth = %d, oldest = %v, err = %v", depth, oldest, err)
	}
}

func TestQueueReadsDeclaredOpenItemsNewestFirst(t *testing.T) {
	conf := testPostgres(t)
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

	page, err := model.Queue(ctx, []forge.Source{read, never}, nil, 500)
	if err != nil {
		t.Fatal(err)
	}
	states, items := page.States, page.Items
	if len(states) != 2 || states[0].Source != read || !states[0].Reachable || states[0].AsOf == nil ||
		states[1].Source != never || states[1].Reachable || states[1].AsOf != nil {
		t.Fatalf("states = %+v", states)
	}
	if len(items) != 2 || items[0].Number != 2 || items[1].Number != 1 || items[0].Source != read || page.Total != 2 {
		t.Fatalf("page = %+v, want open items 2 then 1 of the declared source, 2 in all", page)
	}
}

// Walking the queue page by page returns every open item once, in order, even
// when items share an update time: the key breaks ties by identity.
func TestQueuePagesNeitherSkipNorRepeat(t *testing.T) {
	conf := testPostgres(t)
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
	a := forge.Source{Forge: "github", Owner: "o", Repo: "a"}
	b := forge.Source{Forge: "github", Owner: "o", Repo: "b"}
	t0 := time.Date(2026, 11, 3, 8, 0, 0, 0, time.UTC)
	var seed []forge.Item
	for n := 1; n <= 7; n++ { // n%3 makes several items share each update time
		seed = append(seed, forge.Item{Number: n, Kind: forge.KindIssue, Title: "t", State: "open", Author: "a",
			URL: "u", UpdatedAt: t0.Add(time.Duration(n%3) * time.Minute)})
	}
	for _, s := range []forge.Source{a, b} {
		if err := model.SaveRead(ctx, s, seed, t0); err != nil {
			t.Fatal(err)
		}
	}

	var got []forge.QueueKey
	var after *forge.QueueKey
	for pages := 0; ; pages++ {
		if pages > 14 {
			t.Fatal("the walk does not end")
		}
		page, err := model.Queue(ctx, []forge.Source{a, b}, after, 3)
		if err != nil {
			t.Fatal(err)
		}
		if page.Total != 14 {
			t.Fatalf("total = %d, want 14", page.Total)
		}
		if len(page.Items) == 0 {
			break
		}
		for _, it := range page.Items {
			got = append(got, it.Key())
		}
		last := page.Items[len(page.Items)-1].Key()
		after = &last
	}
	if len(got) != 14 {
		t.Fatalf("walked %d items, want 14: %+v", len(got), got)
	}
	seen := map[forge.QueueKey]bool{}
	for i, k := range got {
		if seen[k] {
			t.Fatalf("item %+v repeated", k)
		}
		seen[k] = true
		if i > 0 && k.UpdatedAt.After(got[i-1].UpdatedAt) {
			t.Fatalf("item %d is newer than the one before it", i)
		}
	}
}

// flakyReader answers its items until it is told the forge is down.
type flakyReader struct {
	items []forge.Item
	down  bool
}

func (f *flakyReader) ListItems(_ context.Context, s forge.Source, _ time.Time) ([]forge.Item, error) {
	if f.down {
		return nil, &forge.SourceError{Source: s, Err: errors.New("connection refused")}
	}
	return f.items, nil
}

// CONSOLE-004 AC1: a forge that goes down after a good read is shown as
// unreachable with that read's time, and its items stay on the page. Through the
// reconciler and the real SQL, because "never empty" is a property of both.
func TestADownSourceShowsItsLastReadNeverEmpty(t *testing.T) {
	conf := testPostgres(t)
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
		t.Fatal(err)
	}
	src := forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}
	read := time.Date(2026, 11, 6, 8, 0, 0, 0, time.UTC)
	now := read
	reader := &flakyReader{items: []forge.Item{{Number: 7, Kind: forge.KindIssue, Title: "t", State: "open",
		Author: "a", URL: "u", UpdatedAt: read}}}
	r := forge.Reconciler{Readers: map[string]forge.Reader{"gitea": reader}, Catalog: &forge.Catalog{Declared: []forge.Source{src}},
		Model: store.ForgeModel{Conf: conf}, Now: func() time.Time { return now }}

	if failed := r.Once(ctx); len(failed) != 0 {
		t.Fatalf("first read failed: %v", failed)
	}
	reader.down, now = true, read.Add(time.Hour)
	if failed := r.Once(ctx); len(failed) != 1 {
		t.Fatalf("down forge not reported: %v", failed)
	}

	page, err := store.ForgeModel{Conf: conf}.Queue(ctx, []forge.Source{src}, nil, 500)
	if err != nil {
		t.Fatal(err)
	}
	if len(page.States) != 1 || page.States[0].Reachable || page.States[0].AsOf == nil ||
		!page.States[0].AsOf.Equal(read) {
		t.Fatalf("state = %+v, want unreachable as of %v", page.States, read)
	}
	if len(page.Items) != 1 || page.Items[0].Number != 7 || page.Total != 1 {
		t.Fatalf("page = %+v, want the last read's item", page)
	}
}

// The sources the store has read seed the catalog at start (AC1): a pod that cannot
// list its forge still serves every repository it read before.
func TestForgeModelListsTheSourcesItHasRead(t *testing.T) {
	conf := testPostgres(t)
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
		t.Fatal(err)
	}
	m := store.ForgeModel{Conf: conf}
	read := forge.Source{Forge: "github", Owner: "o", Repo: "read"}
	down := forge.Source{Forge: "gitea", Owner: "t", Repo: "down"}
	if err := m.SaveRead(ctx, read, nil, time.Now()); err != nil {
		t.Fatal(err)
	}
	if err := m.MarkUnreachable(ctx, down, time.Now()); err != nil {
		t.Fatal(err)
	}
	got, err := m.Sources(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0] != down || got[1] != read {
		t.Fatalf("got %v, want [%v %v]", got, down, read)
	}
}

// A8 reads days of use, so a second visit on the same UTC day must not add a row, and a
// visit just after midnight UTC must.
func TestConsoleUsageCountsOneRowPerIdentityAndUTCDay(t *testing.T) {
	conf := testPostgres(t)
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, `DELETE FROM console_usage WHERE identity = 'usage-test'`); err != nil {
		t.Fatal(err)
	}
	denver := time.FixedZone("MST", -7*3600)
	visits := []struct {
		at        time.Time
		wantFirst bool
	}{
		{time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC), true},
		{time.Date(2026, 11, 12, 23, 59, 0, 0, time.UTC), false},
		{time.Date(2026, 11, 12, 17, 30, 0, 0, denver), true}, // 00:30 UTC on the 13th
	}
	for _, v := range visits {
		first, err := store.RecordConsoleDay(ctx, conf, "usage-test", v.at)
		if err != nil {
			t.Fatal(err)
		}
		if first != v.wantFirst {
			t.Fatalf("RecordConsoleDay(%s) first = %v, want %v", v.at, first, v.wantFirst)
		}
	}
	var days []string
	rows, err := conn.Query(ctx, `SELECT day::text FROM console_usage WHERE identity = 'usage-test' ORDER BY day`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var d string
		if err := rows.Scan(&d); err != nil {
			t.Fatal(err)
		}
		days = append(days, d)
	}
	if len(days) != 2 || days[0] != "2026-11-12" || days[1] != "2026-11-13" {
		t.Fatalf("days = %v, want [2026-11-12 2026-11-13]", days)
	}
}
