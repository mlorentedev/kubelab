package forge

import (
	"context"
	"errors"
	"fmt"
	"log"
	"time"
)

// The outbox worker (CONSOLE-004 AC2, ADR-066 W2-W4 and W8-W9): it takes the rows the routes
// enqueued, sends each to its forge, and settles the row from what the forge answered.

const (
	// WritePeriod is how often the worker looks for a due row. A write is pending in the view
	// until then, so it bounds the latency of a click.
	WritePeriod = 5 * time.Second
	// CallTimeout bounds one call to a forge. The writers' HTTP clients have no timeout of their own.
	CallTimeout = 20 * time.Second
	// SettleInterval is W8's: longer than the longest a forge may spend on one write. A client
	// that gave up does not end the forge's work, so the marker search for a create of unknown
	// outcome waits until the original request has ended. It must exceed CallTimeout by a margin,
	// since the request may have started late in the call.
	SettleInterval = 2 * time.Minute
	// maxPerRun bounds one run, so a long queue never holds the loop away from its context.
	maxPerRun = 50

	backoffBase = 10 * time.Second
	backoffCap  = 15 * time.Minute
	// retryAfterCap bounds what a forge may ask for, so a bad header cannot park a write for days.
	retryAfterCap = time.Hour
	// maxErrorLen bounds the text kept as a row's last_error.
	maxErrorLen = 500
)

// Backoff is the wait before the nth call of a row after a failed one (W3): 10 seconds, doubling,
// 15 minutes at most. A row is never given up on: an unreachable forge leaves the write pending
// and visible (A6), not dropped.
func Backoff(attempts int) time.Duration {
	if attempts < 1 {
		attempts = 1
	}
	if attempts > 8 {
		return backoffCap
	}
	return min(backoffBase<<(attempts-1), backoffCap)
}

// Worker sends the outbox to the forges. The gate (ADR-066 W14) is Writers: a forge with no
// writer is not written to, whatever the rows say.
type Worker struct {
	Store   OutboxStore
	Writers map[string]Writer
	Now     func() time.Time // nil is time.Now
	// Settle and CallTimeout default to SettleInterval and CallTimeout.
	Settle      time.Duration
	CallTimeout time.Duration
	// Backoff defaults to the package's.
	Backoff func(attempts int) time.Duration
}

func (w *Worker) now() time.Time {
	if w.Now != nil {
		return w.Now()
	}
	return time.Now()
}

// hold is how long a claimed row stays out of reach of every worker: the call's own timeout,
// which bounds how long this worker waits for the forge, plus the settle interval that follows
// it (W8). The forge may keep working on a request after its client gave up, so a row is taken
// again, by this worker or by another replica, only once the interval has passed since the
// client stopped waiting, not since the claim.
func (w *Worker) hold() time.Duration {
	return w.callTimeout() + w.settle()
}

func (w *Worker) settle() time.Duration {
	if w.Settle > 0 {
		return w.Settle
	}
	return SettleInterval
}

func (w *Worker) callTimeout() time.Duration {
	if w.CallTimeout > 0 {
		return w.CallTimeout
	}
	return CallTimeout
}

func (w *Worker) backoff(attempts int) time.Duration {
	if w.Backoff != nil {
		return w.Backoff(attempts)
	}
	return Backoff(attempts)
}

// Run works the outbox every period until ctx ends.
func (w *Worker) Run(ctx context.Context, period time.Duration) {
	ticker := time.NewTicker(period)
	defer ticker.Stop()
	for {
		if _, err := w.Once(ctx); err != nil {
			log.Printf("forge write: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// Once sends every row that is due, one at a time, and returns how many it took. A row whose
// settling fails to be recorded is left as it was claimed (in_flight), and is resolved when its
// stamp passes: for a create by its marker, so a crash after the forge's 2xx never opens a
// second issue (W4).
func (w *Worker) Once(ctx context.Context) (int, error) {
	// The marker search is only sound if the original request has ended by the time it runs.
	if w.settle() <= w.callTimeout() {
		return 0, fmt.Errorf("the settle interval %s does not exceed the call timeout %s", w.settle(), w.callTimeout())
	}
	taken := 0
	for taken < maxPerRun && ctx.Err() == nil {
		q, err := w.Store.Claim(ctx, w.now(), w.hold())
		if err != nil {
			return taken, fmt.Errorf("claim: %w", err)
		}
		if q == nil {
			return taken, nil
		}
		taken++
		if err := w.process(ctx, *q); err != nil {
			log.Printf("forge write: outbox %d (%s %s): %v", q.ID, q.Action, q.Source, err)
		}
	}
	return taken, nil
}

func (w *Worker) process(ctx context.Context, q Queued) error {
	writer, err := WriterFor(w.Writers, q.Source.Forge)
	if err != nil {
		// The environment lost its writer after the row was accepted. The row stays owed and
		// in flight; nothing was sent.
		return w.Store.Defer(ctx, q, err, w.now().Add(w.backoff(q.Attempts)))
	}
	if q.Resumed && q.Action == ActionCreate {
		done, err := w.resolve(ctx, writer, &q)
		if done || err != nil {
			return err
		}
	}
	return w.send(ctx, writer, q)
}

// resolve asks the forge whether a create that may have been sent was made (W4, W8). It reports
// whether the row is settled. A create the forge does not have is stamped again and sent by the
// caller; a search that cannot answer leaves the row for a later look, never for a second post.
func (w *Worker) resolve(ctx context.Context, writer Writer, q *Queued) (bool, error) {
	callCtx, cancel := context.WithTimeout(ctx, w.callTimeout())
	defer cancel()
	// SentAt is the row's creation, an earlier time than any send: the search lists every issue
	// changed since, which can only be more than it needs. The settle interval is held by the
	// schedule instead of the lookup: a resumed row is claimed only once its stamp, written at
	// the claim before the send, plus the interval has passed.
	found, err := writer.FindCreated(callCtx, Lookup{Source: q.Source, OutboxID: q.ID, SentAt: q.CreatedAt, Settle: w.settle()})
	var wait *NotSettledError
	switch {
	case errors.As(err, &wait):
		return true, w.Store.Defer(ctx, *q, err, wait.Until)
	case err != nil:
		return true, w.Store.Defer(ctx, *q, err, w.now().Add(w.backoff(q.Attempts)))
	case found.Found:
		return true, w.Store.Applied(ctx, *q, Result{Outcome: OutcomeApplied, Number: found.Number, URL: found.URL}, true, w.now())
	}
	// Not found, and the original request has ended: the create is posted again. The stamp is
	// written before the post, as it is for any send.
	if err := w.Store.Restamp(ctx, q.ID, w.now().Add(w.hold())); err != nil {
		return true, fmt.Errorf("restamp: %w", err)
	}
	q.Attempts++
	return false, nil
}

// send makes the forge call and settles the row from its class.
func (w *Worker) send(ctx context.Context, writer Writer, q Queued) error {
	callCtx, cancel := context.WithTimeout(ctx, w.callTimeout())
	res := writer.Write(callCtx, q.Write())
	cancel()
	at := w.now()
	switch res.Outcome {
	case OutcomeApplied:
		return w.Store.Applied(ctx, q, res, false, at)
	case OutcomeFailed:
		return w.Store.Refused(ctx, q, res, at)
	case OutcomeUnknown:
		if q.Action == ActionCreate {
			return w.Store.Unresolved(ctx, q, res, at)
		}
		// Only a create takes this class; any other write is safe to repeat.
	}
	wait := w.backoff(q.Attempts)
	if res.RetryAfter > wait {
		wait = min(res.RetryAfter, retryAfterCap)
	}
	return w.Store.Retry(ctx, q, res, at.Add(wait), at)
}

// ErrorText is what a row keeps of a failure, cut short.
func ErrorText(err error) string {
	if err == nil {
		return ""
	}
	s := err.Error()
	if len(s) > maxErrorLen {
		s = s[:maxErrorLen]
	}
	return s
}
