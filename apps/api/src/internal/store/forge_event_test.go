package store_test

import (
	"context"
	"os"
	"strconv"
	"testing"

	"github.com/jackc/pgx/v5"
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
