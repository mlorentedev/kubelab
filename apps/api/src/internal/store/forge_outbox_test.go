package store_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// The write outbox and its audit table (CONSOLE-004 AC2). What these tests hold lives in
// the schema, so they run against Postgres like the rest of the store's.

func outboxConn(t *testing.T) (context.Context, *pgx.Conn) {
	t.Helper()
	ctx, conn := statsConn(t)
	if _, err := conn.Exec(ctx, `TRUNCATE forge_outbox, forge_write_audit`); err != nil {
		t.Fatal(err)
	}
	return ctx, conn
}

// insertOutbox adds one row and returns the error, so a test can look at the SQLSTATE.
func insertOutbox(ctx context.Context, conn *pgx.Conn, actor, key, action, status string) error {
	_, err := conn.Exec(ctx, `INSERT INTO forge_outbox
		(actor, idempotency_key, request_hash, forge, owner, repo, action, payload, status)
		VALUES ($1, $2, 'h', 'gitea', 'o', 'r', $3, '{}', $4)`, actor, key, action, status)
	return err
}

func sqlState(err error) string {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.Code
	}
	return ""
}

// The key is unique per actor: a replay by the same actor finds its row, and two actors
// may pick the same key without meeting.
func TestOutboxKeyIsUniquePerActor(t *testing.T) {
	ctx, conn := outboxConn(t)
	if err := insertOutbox(ctx, conn, "manu", "k1", "create", "pending"); err != nil {
		t.Fatal(err)
	}
	if err := insertOutbox(ctx, conn, "n8n", "k1", "create", "pending"); err != nil {
		t.Fatalf("the same key from another actor was refused: %v", err)
	}
	err := insertOutbox(ctx, conn, "manu", "k1", "close", "pending")
	if sqlState(err) != "23505" {
		t.Fatalf("the same key from the same actor: err = %v, want a unique violation", err)
	}
}

// Postgres treats NULLs as distinct, so a nullable key or actor would slip past the UNIQUE
// constraint and the same request could be written twice.
func TestOutboxRefusesAWriteWithoutItsIdentity(t *testing.T) {
	ctx, conn := outboxConn(t)
	for _, column := range []string{"actor", "idempotency_key", "request_hash"} {
		args := map[string]any{"actor": "manu", "idempotency_key": "k", "request_hash": "h"}
		args[column] = nil
		_, err := conn.Exec(ctx, `INSERT INTO forge_outbox
			(actor, idempotency_key, request_hash, forge, owner, repo, action, payload, status)
			VALUES ($1, $2, $3, 'gitea', 'o', 'r', 'create', '{}', 'pending')`,
			args["actor"], args["idempotency_key"], args["request_hash"])
		if sqlState(err) != "23502" {
			t.Errorf("a NULL %s: err = %v, want a not-null violation", column, err)
		}
	}
}

// A value outside the declared sets is refused by the database, so a worker or a handler
// that drifts from the vocabulary fails at the insert and not later, at a forge.
func TestOutboxRefusesWhatItDoesNotDeclare(t *testing.T) {
	ctx, conn := outboxConn(t)
	for _, c := range []struct{ name, action, status string }{
		{"merge is not a write", "merge", "pending"},
		{"review is not a write", "submit_review", "pending"},
		{"unknown status", "create", "done"},
	} {
		if err := insertOutbox(ctx, conn, "manu", c.name, c.action, c.status); sqlState(err) != "23514" {
			t.Errorf("%s: err = %v, want a check violation", c.name, err)
		}
	}
	for _, action := range []string{"create", "add_label", "remove_label", "add_assignee", "remove_assignee", "close", "reopen"} {
		if err := insertOutbox(ctx, conn, "manu", "ok-"+action, action, "pending"); err != nil {
			t.Errorf("declared action %s was refused: %v", action, err)
		}
	}
	for _, status := range []string{"in_flight", "applied", "failed"} {
		if err := insertOutbox(ctx, conn, "manu", "ok-"+status, "close", status); err != nil {
			t.Errorf("declared status %s was refused: %v", status, err)
		}
	}
	_, err := conn.Exec(ctx, `INSERT INTO forge_write_audit (outbox_id, actor, action, forge, owner, repo, outcome)
		VALUES (1, 'manu', 'close', 'gitea', 'o', 'r', 'pending')`)
	if sqlState(err) != "23514" {
		t.Errorf("audit outcome pending: err = %v, want a check violation", err)
	}
}

// Neither table is a cache. Emptying every read-model table the strongest way, CASCADE, is
// what a rebuild may do, and a write that was accepted and not yet delivered, or who asked
// for it, must survive it. A foreign key to the read model would take the rows with it.
func TestRebuildOfTheReadModelKeepsOutboxAndAudit(t *testing.T) {
	ctx, conn := outboxConn(t)
	// The rows name a repository that is in no forge_source: a create may target one the
	// read model has not met, and the outbox must accept it all the same.
	if err := insertOutbox(ctx, conn, "manu", "k1", "create", "pending"); err != nil {
		t.Fatalf("outbox row for a repository the read model does not know: %v", err)
	}
	if _, err := conn.Exec(ctx, `INSERT INTO forge_write_audit (outbox_id, actor, action, forge, owner, repo, outcome, forge_status)
		VALUES (424242, 'manu', 'create', 'gitea', 'o', 'r', 'applied', 201)`); err != nil {
		t.Fatalf("audit row for an outbox row that does not exist: %v", err)
	}
	if _, err := conn.Exec(ctx, `INSERT INTO forge_source (forge, owner, repo) VALUES ('gitea', 'o', 'r')`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(ctx, `TRUNCATE forge_source, forge_item, forge_event CASCADE`); err != nil {
		t.Fatal(err)
	}
	var outbox, audit int
	if err := conn.QueryRow(ctx, `SELECT (SELECT count(*) FROM forge_outbox), (SELECT count(*) FROM forge_write_audit)`).Scan(&outbox, &audit); err != nil {
		t.Fatal(err)
	}
	if outbox != 1 || audit != 1 {
		t.Fatalf("after a read-model rebuild: outbox rows = %d, audit rows = %d, want 1 and 1", outbox, audit)
	}
	var foreignKeys int
	err := conn.QueryRow(ctx, `SELECT count(*) FROM pg_constraint
		WHERE contype = 'f' AND conrelid IN ('forge_outbox'::regclass, 'forge_write_audit'::regclass)`).Scan(&foreignKeys)
	if err != nil {
		t.Fatal(err)
	}
	if foreignKeys != 0 {
		t.Fatalf("outbox and audit hold %d foreign keys, want none", foreignKeys)
	}
}

// The worker scans rows still owed to a forge. Its index must be the one that answers
// that query, and must not hold the settled rows, which are most of the table over time.
func TestOutboxWorkerScanUsesThePartialIndex(t *testing.T) {
	ctx, conn := outboxConn(t)
	for i, status := range []string{"pending", "in_flight", "applied", "applied", "failed"} {
		if err := insertOutbox(ctx, conn, "manu", string(rune('a'+i)), "close", status); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := conn.Exec(ctx, `ANALYZE forge_outbox`); err != nil {
		t.Fatal(err)
	}
	// A five-row table is cheaper to scan than to index, so the planner is told not to
	// prefer the scan: the question is whether the index can answer, not whether it wins.
	if _, err := conn.Exec(ctx, `SET enable_seqscan = off`); err != nil {
		t.Fatal(err)
	}
	var plan string
	err := conn.QueryRow(ctx, `EXPLAIN (FORMAT JSON) SELECT id FROM forge_outbox
		WHERE status IN ('pending', 'in_flight') AND next_attempt_at <= now() ORDER BY next_attempt_at`).Scan(&plan)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(plan, `"Index Name": "forge_outbox_due"`) {
		t.Fatalf("the worker's scan does not use forge_outbox_due: %s", plan)
	}
	var settledIndexed int
	err = conn.QueryRow(ctx, `SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
		WHERE c.relname = 'forge_outbox_due' AND i.indpred IS NOT NULL`).Scan(&settledIndexed)
	if err != nil {
		t.Fatal(err)
	}
	if settledIndexed != 1 {
		t.Fatal("forge_outbox_due is not a partial index: it would hold every settled row")
	}
}
