package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The write outbox on Postgres (CONSOLE-004 AC2, ADR-066 W1-W9). ForgeModel is the worker's
// forge.OutboxStore. Neither table has a foreign key to the read model (W6), so settling a row
// writes the read model by hand, in the same transaction as the row.

var _ forge.OutboxStore = ForgeModel{}

// Enqueue keeps an accepted write, once per (actor, key). A replay of the same request returns the
// earlier row, whatever state it has reached; the same key with a different request is
// forge.ErrKeyReuse and writes nothing. The unique constraint, not a read before the insert, is
// what makes two simultaneous requests with one key make one row.
func (m ForgeModel) Enqueue(ctx context.Context, e forge.Enqueue) (forge.Receipt, error) {
	db, err := Pool(m.Conf)
	if err != nil {
		return forge.Receipt{}, err
	}
	payload, err := json.Marshal(e.Payload)
	if err != nil {
		return forge.Receipt{}, err
	}
	var id int64
	err = db.QueryRow(ctx, `INSERT INTO forge_outbox
		(actor, idempotency_key, request_hash, forge, owner, repo, number, action, payload, status)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
		ON CONFLICT (actor, idempotency_key) DO NOTHING RETURNING id`,
		e.Actor, e.Key, e.Hash, e.Source.Forge, e.Source.Owner, e.Source.Repo, nilIfZero(e.Number),
		string(e.Action), payload).Scan(&id)
	if err == nil {
		return forge.Receipt{ID: id, Status: forge.StatusPending}, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return forge.Receipt{}, err
	}
	var hash string
	r := forge.Receipt{Replay: true}
	var lastError *string
	if err := db.QueryRow(ctx, `SELECT id, request_hash, status, response, last_error FROM forge_outbox
		WHERE actor = $1 AND idempotency_key = $2`, e.Actor, e.Key).
		Scan(&r.ID, &hash, &r.Status, &r.Response, &lastError); err != nil {
		return forge.Receipt{}, err
	}
	if hash != e.Hash {
		return forge.Receipt{}, forge.ErrKeyReuse
	}
	if lastError != nil {
		r.LastError = *lastError
	}
	return r, nil
}

// Claim takes the oldest due row that may be sent. See forge.OutboxStore.
//
// `FOR UPDATE SKIP LOCKED` is what lets two workers share the table: a row another worker holds
// is passed over, never waited for. The NOT EXISTS keeps one issue's writes in order and apart:
// a row waits while any earlier row for the same issue is still pending or in flight, which
// includes one backing off. A create has no issue number yet and waits for nothing.
func (m ForgeModel) Claim(ctx context.Context, now time.Time, hold time.Duration) (*forge.Queued, error) {
	db, err := Pool(m.Conf)
	if err != nil {
		return nil, err
	}
	var (
		q       forge.Queued
		action  string
		number  *int
		payload []byte
		was     string
	)
	err = db.QueryRow(ctx, `WITH due AS (
			SELECT o.id, o.status AS was FROM forge_outbox o
			WHERE o.status IN ('pending', 'in_flight') AND o.next_attempt_at <= $1
			  AND (o.number IS NULL OR NOT EXISTS (
			      SELECT 1 FROM forge_outbox e
			      WHERE e.forge = o.forge AND e.owner = o.owner AND e.repo = o.repo AND e.number = o.number
			        AND e.status IN ('pending', 'in_flight') AND e.id < o.id))
			ORDER BY o.id LIMIT 1
			FOR UPDATE OF o SKIP LOCKED)
		UPDATE forge_outbox o
		SET status = 'in_flight', next_attempt_at = $2,
		    attempts = o.attempts + CASE WHEN due.was = 'in_flight' AND o.action = 'create' THEN 0 ELSE 1 END
		FROM due WHERE o.id = due.id
		RETURNING o.id, o.actor, o.action, o.forge, o.owner, o.repo, o.number, o.payload, o.attempts, o.created_at, due.was`,
		now, now.Add(hold)).
		Scan(&q.ID, &q.Actor, &action, &q.Source.Forge, &q.Source.Owner, &q.Source.Repo, &number, &payload,
			&q.Attempts, &q.CreatedAt, &was)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	q.Action = forge.Action(action)
	if number != nil {
		q.Number = *number
	}
	if err := json.Unmarshal(payload, &q.Payload); err != nil {
		return nil, fmt.Errorf("outbox %d: payload: %w", q.ID, err)
	}
	q.Resumed = was == forge.StatusInFlight
	return &q, nil
}

// Restamp moves a row's next_attempt_at out and counts the call it stamps. GREATEST: a stamp
// only ever moves later, so no update can make an in_flight create due before the interval
// that follows its send has passed (W8).
func (m ForgeModel) Restamp(ctx context.Context, id int64, until time.Time) error {
	db, err := Pool(m.Conf)
	if err != nil {
		return err
	}
	_, err = db.Exec(ctx, `UPDATE forge_outbox SET next_attempt_at = GREATEST(next_attempt_at, $2), attempts = attempts + 1
		WHERE id = $1 AND status = 'in_flight'`, id, until)
	return err
}

// Applied settles a row the forge confirmed.
func (m ForgeModel) Applied(ctx context.Context, q forge.Queued, res forge.Result, adopted bool, at time.Time) error {
	number := q.Number
	var response []byte
	if q.Action == forge.ActionCreate {
		number = res.Number
		response, _ = json.Marshal(map[string]any{"number": res.Number, "url": res.URL})
	}
	return m.settle(ctx, q, number, res, adopted, at, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `UPDATE forge_outbox SET status = 'applied', response = $2, applied_at = $3,
			number = $4, last_error = NULL WHERE id = $1`, q.ID, response, at, nilIfZero(number)); err != nil {
			return err
		}
		return applyToReadModel(ctx, tx, q, number, res.URL, at)
	})
}

// Refused settles a row for good.
func (m ForgeModel) Refused(ctx context.Context, q forge.Queued, res forge.Result, at time.Time) error {
	return m.settle(ctx, q, q.Number, res, false, at, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `UPDATE forge_outbox SET status = 'failed', last_error = $2 WHERE id = $1`,
			q.ID, forge.ErrorText(res.Err))
		return err
	})
}

// Retry puts a row back to pending, due at next.
func (m ForgeModel) Retry(ctx context.Context, q forge.Queued, res forge.Result, next, at time.Time) error {
	return m.settle(ctx, q, q.Number, res, false, at, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `UPDATE forge_outbox SET status = 'pending', next_attempt_at = $2, last_error = $3
			WHERE id = $1`, q.ID, next, forge.ErrorText(res.Err))
		return err
	})
}

// Unresolved keeps a create of unknown outcome in flight. Its next_attempt_at is not touched:
// the stamp written before the send is what the settle interval is counted from.
func (m ForgeModel) Unresolved(ctx context.Context, q forge.Queued, res forge.Result, at time.Time) error {
	return m.settle(ctx, q, q.Number, res, false, at, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `UPDATE forge_outbox SET last_error = $2 WHERE id = $1`,
			q.ID, forge.ErrorText(res.Err))
		return err
	})
}

// Defer keeps an in_flight row for a later look. It makes no audit row: nothing was written to a
// forge. GREATEST for the reason Restamp has it.
func (m ForgeModel) Defer(ctx context.Context, q forge.Queued, cause error, next time.Time) error {
	db, err := Pool(m.Conf)
	if err != nil {
		return err
	}
	_, err = db.Exec(ctx, `UPDATE forge_outbox SET next_attempt_at = GREATEST(next_attempt_at, $2), last_error = $3
		WHERE id = $1`, q.ID, next, forge.ErrorText(cause))
	return err
}

// settle runs one settling in a transaction: the audit row for the call, then what the caller
// changes of the row and the read model. A call that settled nothing leaves its audit row too.
func (m ForgeModel) settle(ctx context.Context, q forge.Queued, number int, res forge.Result, adopted bool, at time.Time,
	change func(pgx.Tx) error) error {
	db, err := Pool(m.Conf)
	if err != nil {
		return err
	}
	return pgx.BeginFunc(ctx, db, func(tx pgx.Tx) error {
		var status *int
		if res.Status != 0 && !adopted {
			status = &res.Status
		}
		if _, err := tx.Exec(ctx, `INSERT INTO forge_write_audit
			(outbox_id, actor, action, forge, owner, repo, number, detail, outcome, forge_status, at)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
			q.ID, q.Actor, string(q.Action), q.Source.Forge, q.Source.Owner, q.Source.Repo, nilIfZero(number),
			auditDetail(q), auditOutcome(res.Outcome, adopted), status, at); err != nil {
			return err
		}
		return change(tx)
	})
}

func auditOutcome(o forge.Outcome, adopted bool) string {
	if adopted {
		return string(forge.OutcomeApplied)
	}
	return string(o)
}

// auditDetail is what an audit row says of the write: the label, the login or the title, and
// never the issue's body (which can carry what the operator typed into a private repository).
func auditDetail(q forge.Queued) []byte {
	var d map[string]string
	switch q.Action {
	case forge.ActionCreate:
		d = map[string]string{"title": q.Payload.Title}
	case forge.ActionAddLabel, forge.ActionRemoveLabel:
		d = map[string]string{"label": q.Payload.Label}
	case forge.ActionAddAssignee, forge.ActionRemoveAssignee:
		d = map[string]string{"login": q.Payload.Login}
	default:
		return nil
	}
	raw, _ := json.Marshal(d)
	return raw
}

func nilIfZero(n int) *int {
	if n == 0 {
		return nil
	}
	return &n
}

// applyToReadModel applies a confirmed write to forge_item (W2): the webhook and the reconcile
// only reconcile it, they never settle it. updated_at is not moved: the forge's own change time
// is what a later delivery is compared with, and ours would be ahead of it by the clocks' skew.
// An item the read model has not met is left to the reconcile, except a create, which is the item.
func applyToReadModel(ctx context.Context, tx pgx.Tx, q forge.Queued, number int, url string, at time.Time) error {
	src := q.Source
	switch q.Action {
	case forge.ActionCreate:
		if _, err := tx.Exec(ctx, `INSERT INTO forge_source (forge, owner, repo) VALUES ($1, $2, $3)
			ON CONFLICT (forge, owner, repo) DO NOTHING`, src.Forge, src.Owner, src.Repo); err != nil {
			return err
		}
		// A delivery that arrived first already holds the item, with the forge's own author.
		_, err := tx.Exec(ctx, `INSERT INTO forge_item (forge, owner, repo, number, kind, title, state, author, url, updated_at)
			VALUES ($1, $2, $3, $4, 'issue', $5, 'open', '', $6, $7)
			ON CONFLICT (forge, owner, repo, number) DO NOTHING`,
			src.Forge, src.Owner, src.Repo, number, q.Payload.Title, url, at)
		return err
	case forge.ActionAddLabel:
		return updateItem(ctx, tx, q, `labels = CASE WHEN $5 = ANY(labels) THEN labels ELSE array_append(labels, $5) END`, q.Payload.Label)
	case forge.ActionRemoveLabel:
		return updateItem(ctx, tx, q, `labels = array_remove(labels, $5)`, q.Payload.Label)
	case forge.ActionAddAssignee:
		return updateItem(ctx, tx, q, `assignees = CASE WHEN $5 = ANY(assignees) THEN assignees ELSE array_append(assignees, $5) END`, q.Payload.Login)
	case forge.ActionRemoveAssignee:
		return updateItem(ctx, tx, q, `assignees = array_remove(assignees, $5)`, q.Payload.Login)
	case forge.ActionClose:
		return updateItem(ctx, tx, q, `state = 'closed'`)
	case forge.ActionReopen:
		return updateItem(ctx, tx, q, `state = 'open'`)
	}
	return nil
}

// updateItem sets one column of the item a write named. $5, when the statement has one, is the
// write's label or login.
func updateItem(ctx context.Context, tx pgx.Tx, q forge.Queued, set string, value ...any) error {
	args := append([]any{q.Source.Forge, q.Source.Owner, q.Source.Repo, q.Number}, value...)
	_, err := tx.Exec(ctx, `UPDATE forge_item SET `+set+`
		WHERE forge = $1 AND owner = $2 AND repo = $3 AND number = $4`, args...)
	return err
}

// ItemKind says whether the read model holds an issue or a pull request at a number.
func (m ForgeModel) ItemKind(ctx context.Context, s forge.Source, number int) (forge.Kind, bool, error) {
	db, err := Pool(m.Conf)
	if err != nil {
		return "", false, err
	}
	var kind string
	err = db.QueryRow(ctx, `SELECT kind FROM forge_item WHERE forge = $1 AND owner = $2 AND repo = $3 AND number = $4`,
		s.Forge, s.Owner, s.Repo, number).Scan(&kind)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return forge.Kind(kind), true, nil
}

// maxWrites bounds what the queue lists of the outbox. A backlog past it is an incident the depth
// metric reports, and a page that lists thousands of rows would not be read.
const maxWrites = 500

// Writes lists what the queue shows of the outbox: every row still owed (pending or in flight,
// shown alike) and every failed row whose latest forge call, read from its audit rows, is not
// older than failedSince. The window is the last call and not the queueing: a row that retried
// for a day before the forge refused it is a fresh failure. A failed row with no audit row
// falls back to its creation.
func (m ForgeModel) Writes(ctx context.Context, failedSince time.Time) ([]forge.WriteRow, error) {
	db, err := Pool(m.Conf)
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT o.id, o.action, o.forge, o.owner, o.repo, o.number, o.payload,
			CASE WHEN o.status = 'failed' THEN 'failed' ELSE 'pending' END, o.last_error, o.created_at
		FROM forge_outbox o
		WHERE o.status IN ('pending', 'in_flight')
		   OR (o.status = 'failed' AND coalesce(
		        (SELECT max(a.at) FROM forge_write_audit a WHERE a.outbox_id = o.id), o.created_at) >= $1)
		ORDER BY o.id LIMIT $2`, failedSince, maxWrites)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (forge.WriteRow, error) {
		var (
			w       forge.WriteRow
			action  string
			number  *int
			payload []byte
			lastErr *string
		)
		if err := r.Scan(&w.ID, &action, &w.Source.Forge, &w.Source.Owner, &w.Source.Repo, &number, &payload,
			&w.Status, &lastErr, &w.QueuedAt); err != nil {
			return w, err
		}
		w.Action = forge.Action(action)
		if number != nil {
			w.Number = *number
		}
		if lastErr != nil {
			w.LastError = *lastErr
		}
		var p forge.Payload
		if err := json.Unmarshal(payload, &p); err != nil {
			return w, fmt.Errorf("outbox %d: payload: %w", w.ID, err)
		}
		switch w.Action {
		case forge.ActionCreate:
			w.Detail = p.Title
		case forge.ActionAddLabel, forge.ActionRemoveLabel:
			w.Detail = p.Label
		case forge.ActionAddAssignee, forge.ActionRemoveAssignee:
			w.Detail = p.Login
		}
		return w, nil
	})
}
