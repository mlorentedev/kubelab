package store_test

import (
	"context"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
)

// The forge_stats view is what Grafana's read-only role selects (CONSOLE-004 AC6). The role
// holds nothing on the tables, so what the view returns is everything it can ever read.

func statsConn(t *testing.T) (context.Context, *pgx.Conn) {
	t.Helper()
	conf := testPostgres(t)
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, conf.DSN())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close(ctx) })
	return ctx, conn
}

func TestForgeStatsExposesCountsAndNoIdentifyingColumn(t *testing.T) {
	ctx, conn := statsConn(t)
	rows, err := conn.Query(ctx, `SELECT column_name FROM information_schema.columns
		WHERE table_name = 'forge_stats' AND table_schema = 'public'`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var got []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatal(err)
		}
		got = append(got, name)
	}
	sort.Strings(got)
	// An allow-list, not a deny-list: a column added to the view later fails here until it is
	// judged. title, url, author, assignees, labels (free text) and number (owner, repo and
	// number rebuild an item's address) are all left out on purpose.
	want := []string{
		"area", "as_of", "forge", "kind", "last_attempt_at", "owner", "priority", "repo",
		"source_reachable", "state", "status", "updated_at",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("forge_stats columns = %v, want %v", got, want)
	}
}

func TestForgeStatsRunsWithTheOwnersRightsNotTheCallers(t *testing.T) {
	ctx, conn := statsConn(t)
	var options []string
	err := conn.QueryRow(ctx, `SELECT coalesce(reloptions, '{}') FROM pg_class WHERE relname = 'forge_stats'`).Scan(&options)
	if err != nil {
		t.Fatal(err)
	}
	// security_invoker would make the role need SELECT on forge_item, which is the grant this
	// view exists to avoid.
	if strings.Contains(strings.Join(options, ","), "security_invoker") {
		t.Fatalf("forge_stats is security_invoker: %v", options)
	}
}

func TestForgeStatsDerivesTheThreeLabelsAndKeepsAnEmptySource(t *testing.T) {
	ctx, conn := statsConn(t)
	model := store.ForgeModel{Conf: testPostgres(t)}
	if _, err := conn.Exec(ctx, `TRUNCATE forge_event, forge_item, forge_source`); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 2, 8, 0, 0, 0, time.UTC)
	full := forge.Source{Forge: "github", Owner: "o", Repo: "full"}
	empty := forge.Source{Forge: "github", Owner: "o", Repo: "empty"}
	items := []forge.Item{
		{Number: 1, Kind: forge.KindIssue, Title: "secret title", State: "open", Author: "a", URL: "u",
			Labels: []string{"status:in-progress", "priority:P1", "area:CONSOLE", "free text"}, UpdatedAt: now},
		{Number: 2, Kind: forge.KindPull, Title: "t", State: "closed", Author: "a", URL: "u", UpdatedAt: now},
	}
	if err := model.SaveRead(ctx, full, items, now); err != nil {
		t.Fatal(err)
	}
	if err := model.SaveRead(ctx, empty, nil, now); err != nil {
		t.Fatal(err)
	}

	type row struct{ repo, kind, state, status, priority, area *string }
	rows, err := conn.Query(ctx, `SELECT repo, kind, state, status, priority, area FROM forge_stats ORDER BY repo, kind`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var got []row
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.repo, &r.kind, &r.state, &r.status, &r.priority, &r.area); err != nil {
			t.Fatal(err)
		}
		got = append(got, r)
	}
	str := func(s *string) string {
		if s == nil {
			return "<null>"
		}
		return *s
	}
	var lines []string
	for _, r := range got {
		lines = append(lines, strings.Join([]string{str(r.repo), str(r.kind), str(r.state), str(r.status), str(r.priority), str(r.area)}, "|"))
	}
	want := []string{
		"empty|<null>|<null>|<null>|<null>|<null>",
		"full|issue|open|in-progress|P1|CONSOLE",
		"full|pull|closed|<null>|<null>|<null>",
	}
	if !reflect.DeepEqual(lines, want) {
		t.Fatalf("forge_stats rows = %v, want %v", lines, want)
	}
}
