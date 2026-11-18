package forge

import (
	"context"
	"encoding/json"
	"errors"
	"time"
)

// The outbox's side of the forge package (CONSOLE-004 AC2, ADR-066 W1-W9): the row the worker
// reads, and the store it settles one in. The tables are migrations/20261116000000_forge_write_outbox.sql
// and 20261117000000_forge_write_audit_outcomes.sql.

// The statuses a row holds (the outbox's CHECK list).
const (
	StatusPending  = "pending"
	StatusInFlight = "in_flight"
	StatusApplied  = "applied"
	StatusFailed   = "failed"
)

// Payload is what a row carries of its request besides the target and the action: the jsonb
// column. Only the fields the action uses are set.
type Payload struct {
	Title string `json:"title,omitempty"`
	Body  string `json:"body,omitempty"`
	Label string `json:"label,omitempty"`
	Login string `json:"login,omitempty"`
}

// Queued is one outbox row as the worker sees it.
type Queued struct {
	ID      int64
	Actor   string
	Action  Action
	Source  Source
	Number  int // 0 for a create that the forge has not answered yet
	Payload Payload
	// Attempts counts the forge calls made for the row, a call that was stamped included.
	Attempts  int
	CreatedAt time.Time
	// Resumed is a row found in_flight: an earlier claim may have sent the request and not
	// recorded its answer, because the process ended between the two (ADR-066 W4).
	Resumed bool
}

// Write is the forge request the row stands for.
func (q Queued) Write() Write {
	return Write{
		Action: q.Action, Source: q.Source, Number: q.Number, OutboxID: q.ID,
		Title: q.Payload.Title, Body: q.Payload.Body, Label: q.Payload.Label, Login: q.Payload.Login,
	}
}

// OutboxStore is the worker's view of the outbox. Every time it takes is the worker's clock, never
// the database's: the settle schedule (W8) compares what it writes against what it reads, and two
// clocks would let a row come due earlier than the interval says.
type OutboxStore interface {
	// Claim takes the oldest row that is due and may be sent, nil when there is none. A row is due
	// when its status is pending or in_flight and next_attempt_at has passed; it may be sent when no
	// earlier row of the same forge, repository and issue is still owed (writes to one issue keep
	// their order, and never overlap). The claim commits the row in_flight with next_attempt_at at
	// now+hold before it returns, so the forge is never called for a row the database does not
	// show as in flight, and a row left in flight is not due again until the hold has passed. The
	// worker's hold is the call's timeout plus the settle interval (W8, W16).
	Claim(ctx context.Context, now time.Time, hold time.Duration) (*Queued, error)
	// Restamp moves an in_flight row's next_attempt_at out to until, and counts a call, immediately
	// before the call it stamps. It never moves the time earlier.
	Restamp(ctx context.Context, id int64, until time.Time) error
	// Applied settles the row: the forge confirmed it (W2), or the marker search found the issue
	// a create made (adopted, which makes no call and records no status). It writes the response,
	// one audit row and the change to the read model in one transaction.
	Applied(ctx context.Context, q Queued, res Result, adopted bool, at time.Time) error
	// Refused settles the row for good: the forge refused it, or it cannot be made.
	Refused(ctx context.Context, q Queued, res Result, at time.Time) error
	// Retry puts the row back to pending, due at next.
	Retry(ctx context.Context, q Queued, res Result, next, at time.Time) error
	// Unresolved records a create whose outcome is not known. The row stays in_flight, due at the
	// time its stamp already holds.
	Unresolved(ctx context.Context, q Queued, res Result, at time.Time) error
	// Defer keeps an in_flight row for a later look, after a marker search that could not answer.
	// It never moves next_attempt_at earlier. No call to write was made, so there is no audit row.
	Defer(ctx context.Context, q Queued, cause error, next time.Time) error
}

// Outcomes is every outcome the audit records, held equal to the audit table's CHECK by a test.
var Outcomes = []Outcome{OutcomeApplied, OutcomeFailed, OutcomeRetry, OutcomeUnknown}

// ErrKeyReuse means an Idempotency-Key was sent again with a different request (W1). A route
// answers 422.
var ErrKeyReuse = errors.New("the idempotency key was used with a different request")

// Enqueue is one accepted write: what a route hands the store to keep.
type Enqueue struct {
	Actor string
	// Key is the client's Idempotency-Key. (Actor, Key) is unique.
	Key string
	// Hash is a digest of the whole request, the action and its target included. The same key
	// with another hash is ErrKeyReuse.
	Hash    string
	Action  Action
	Source  Source
	Number  int // 0 for a create
	Payload Payload
}

// Receipt is the row an Enqueue found or made. Replay is true when the key had been used before
// (by the same request): nothing was written, and the row is the earlier one.
type Receipt struct {
	ID     int64
	Status string
	// Response is what the forge answered to an applied write (a created issue's number and url).
	Response  json.RawMessage
	LastError string
	Replay    bool
}

// State is how a row is shown: pending until the forge confirms (A2), whether the worker holds
// it in flight or not.
func (r Receipt) State() string {
	if r.Status == StatusInFlight {
		return StatusPending
	}
	return r.Status
}
