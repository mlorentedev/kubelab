package forge

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// The write side of the forge package (CONSOLE-004 AC2, ADR-066 W1-W9): one interface over
// both forges for the seven actions the outbox allows, and a classification of what the forge
// answered that the worker acts on. Nothing here merges, reviews or requests a reviewer: the
// action set is closed, and an action outside it is refused before any call.

// Action is one write the outbox can hold. The values are the outbox's CHECK list
// (migrations/20261116000000_forge_write_outbox.sql), which a test holds equal to Actions.
type Action string

const (
	ActionCreate         Action = "create"
	ActionAddLabel       Action = "add_label"
	ActionRemoveLabel    Action = "remove_label"
	ActionAddAssignee    Action = "add_assignee"
	ActionRemoveAssignee Action = "remove_assignee"
	ActionClose          Action = "close"
	ActionReopen         Action = "reopen"
)

// Actions is every action a Writer makes.
var Actions = []Action{
	ActionCreate, ActionAddLabel, ActionRemoveLabel, ActionAddAssignee, ActionRemoveAssignee, ActionClose, ActionReopen,
}

// Write is one request to a forge. Source names the repository (a wildcard is refused). Every
// action but a create names an existing issue by Number, and the issue endpoints of both forges
// act on pull requests as well: whether a route lets a pull request through is the route's call.
type Write struct {
	Action Action
	Source Source
	Number int
	// OutboxID is a create's marker (W4): the id of its outbox row, written into the issue's body.
	OutboxID int64
	Title    string
	Body     string
	Label    string // add_label, remove_label
	Login    string // add_assignee, remove_assignee
}

// Outcome is what the worker does next (ADR-066 W3 and W8).
type Outcome string

const (
	// OutcomeApplied: the forge confirmed the change (W2).
	OutcomeApplied Outcome = "applied"
	// OutcomeFailed is terminal: the forge refused the write, or it cannot be made.
	OutcomeFailed Outcome = "failed"
	// OutcomeRetry leaves the row pending. The write either did not reach the forge or is safe to repeat.
	OutcomeRetry Outcome = "retry"
	// OutcomeUnknown is a create that may have been made and whose answer was lost or was not
	// trusted. It is resolved with FindCreated before the create is posted again (W8).
	OutcomeUnknown Outcome = "unknown"
)

// Result is the typed answer to one Write. Status is the HTTP status of the call that decided
// the outcome, 0 when the forge gave no answer or no call was made. Number and URL are a
// create's issue. RetryAfter is what the forge asked for, when it asked.
type Result struct {
	Outcome    Outcome
	Status     int
	Number     int
	URL        string
	RetryAfter time.Duration
	Err        error
}

// Lookup asks a forge for the issue a create made, by its marker (W4, W8). SentAt is when the
// create was last sent, and Settle the interval after it that is longer than the forge may spend
// on one write: until it has passed, a listing that lacks the marker proves nothing, because the
// original request may still be running. The value of Settle is the worker's.
type Lookup struct {
	Source   Source
	OutboxID int64
	SentAt   time.Time
	Settle   time.Duration
}

// LookupResult is the issue carrying the marker, when there is one.
type LookupResult struct {
	Found  bool
	Number int
	URL    string
}

// NotSettledError answers a lookup that found nothing before the settle interval ended: ask
// again at Until. It is a wait, never "not found".
type NotSettledError struct{ Until time.Time }

func (e *NotSettledError) Error() string {
	return "no issue carries the marker yet; the create may still be running until " + e.Until.UTC().Format(time.RFC3339)
}

// ErrNoWriter means there is no writer for a forge: its credential is not configured, as in
// staging, which has none (ADR-066 W7). A route answers 503 on it.
var ErrNoWriter = errors.New("no writer for this forge")

// Writer makes the writes of one forge.
type Writer interface {
	// Write makes one request and classifies the answer. It never returns a bare error: every
	// failure is a Result the worker can act on.
	Write(ctx context.Context, w Write) Result
	// FindCreated looks for the issue whose body carries the marker of lk.OutboxID. A not-found
	// answer (Found false, nil error) is authoritative; any other doubt is an error.
	FindCreated(ctx context.Context, lk Lookup) (LookupResult, error)
}

// WriterFor picks the writer of a forge, or ErrNoWriter when the environment configured none.
func WriterFor(writers map[string]Writer, name string) (Writer, error) {
	if w, ok := writers[name]; ok && w != nil {
		return w, nil
	}
	return nil, fmt.Errorf("%w: %s", ErrNoWriter, name)
}

// Marker is the hidden comment a create's body ends with, so the issue can be found without an
// issue number. The closing comment mark makes it exact: outbox 12 never matches outbox 123.
func Marker(outboxID int64) string {
	return "<!-- kubelab-write:" + strconv.FormatInt(outboxID, 10) + " -->"
}

// validate refuses a write that cannot be made well-formed, before any call.
func (w Write) validate() error {
	known := false
	for _, a := range Actions {
		known = known || a == w.Action
	}
	if !known {
		return fmt.Errorf("unknown action %q", w.Action)
	}
	if err := w.Source.validForWrite(); err != nil {
		return err
	}
	switch w.Action {
	case ActionCreate:
		if strings.TrimSpace(w.Title) == "" {
			return errors.New("create needs a title")
		}
		if w.OutboxID <= 0 {
			return errors.New("create needs the outbox id its marker carries")
		}
		return nil
	case ActionAddLabel, ActionRemoveLabel:
		if w.Label == "" {
			return fmt.Errorf("%s needs a label", w.Action)
		}
	case ActionAddAssignee, ActionRemoveAssignee:
		if w.Login == "" {
			return fmt.Errorf("%s needs a login", w.Action)
		}
	}
	if w.Number <= 0 {
		return fmt.Errorf("%s needs an issue number", w.Action)
	}
	return nil
}

func (s Source) validForWrite() error {
	if s.Owner == "" || s.Repo == "" || s.Wildcard() {
		return fmt.Errorf("a write needs one repository, got %s/%s", s.Owner, s.Repo)
	}
	return nil
}

func (l Lookup) validate() error {
	if err := l.Source.validForWrite(); err != nil {
		return err
	}
	if l.OutboxID <= 0 {
		return errors.New("lookup needs an outbox id")
	}
	if l.SentAt.IsZero() {
		return errors.New("lookup needs the time the create was sent")
	}
	return nil
}

// reply is one HTTP exchange: either an error with no answer, or a status with its body.
type reply struct {
	Status int
	Header http.Header
	Body   []byte
	Err    error
}

func (r reply) ok() bool { return r.Err == nil && r.Status/100 == 2 }

// maxReplyBytes bounds what is read of an answer: an issue's JSON is far smaller.
const maxReplyBytes = 4 << 20

// call sends one request and reads its answer. A redirect is never followed: Go re-issues a
// redirected POST, PATCH or DELETE as a GET, whose 200 would read as a write that applied
// (GitHub answers a moved repository with a 301), and the token would follow it.
func call(ctx context.Context, client *http.Client, auth func(*http.Request), method, url string, body any) reply {
	var rd io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return reply{Err: fmt.Errorf("encode request: %w", err)}
		}
		rd = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, rd)
	if err != nil {
		return reply{Err: fmt.Errorf("build request: %w", err)}
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	auth(req)
	if client == nil {
		client = http.DefaultClient
	}
	noRedirect := *client
	noRedirect.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	resp, err := noRedirect.Do(req)
	if err != nil {
		return reply{Err: err}
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxReplyBytes))
	if err != nil {
		// The status line arrived, so the forge did answer; the body did not.
		return reply{Status: resp.StatusCode, Header: resp.Header, Err: fmt.Errorf("read answer: %w", err)}
	}
	return reply{Status: resp.StatusCode, Header: resp.Header, Body: raw}
}

// failure classifies an exchange that did not confirm a write (ADR-066 W3, W8).
//
// A definite refusal is terminal: a 4xx other than 429 and a rate-limit 403, and a redirect,
// which the forge answers before it acts. A network error, a 5xx, a 429 and a rate-limit 403 are
// retryable, except for a create, which may have been made: that is UNKNOWN until its marker is
// searched. The one create that is retryable is one that provably sent nothing: the call
// ceiling refused it, or no token minted.
func (r reply) failure(create bool) Result {
	res := Result{Status: r.Status, RetryAfter: r.retryAfter(), Err: r.Err}
	retry := OutcomeRetry
	if create {
		retry = OutcomeUnknown
	}
	switch {
	case r.Err != nil && r.Status == 0 && errors.Is(r.Err, ErrCeiling):
		res.Outcome = OutcomeRetry
	case r.Err != nil:
		res.Outcome = retry
	case r.Status/100 == 3:
		res.Outcome = OutcomeFailed
		res.Err = fmt.Errorf("forge answered %d: the repository has moved, update the source", r.Status)
	case r.rateLimited():
		res.Outcome, res.Err = retry, r.statusError()
	case r.Status/100 == 4:
		res.Outcome, res.Err = OutcomeFailed, r.statusError()
	default:
		res.Outcome, res.Err = retry, r.statusError()
	}
	return res
}

// rateLimited reports a forge's own limit: 429, or the 403 GitHub sends for its primary
// (X-RateLimit-Remaining 0) and secondary (Retry-After) limits.
func (r reply) rateLimited() bool {
	if r.Status == http.StatusTooManyRequests {
		return true
	}
	return r.Status == http.StatusForbidden && (r.Header.Get("Retry-After") != "" || r.Header.Get("X-RateLimit-Remaining") == "0")
}

func (r reply) retryAfter() time.Duration {
	secs, err := strconv.Atoi(r.Header.Get("Retry-After"))
	if err != nil || secs < 0 {
		return 0
	}
	return time.Duration(secs) * time.Second
}

// statusError names the status and, when the forge sent one, its message (both forges answer
// {"message": ...}), cut short. Nothing of the request is echoed.
func (r reply) statusError() error {
	var body struct {
		Message string `json:"message"`
	}
	if json.Unmarshal(r.Body, &body) == nil && body.Message != "" {
		msg := body.Message
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return fmt.Errorf("forge answered %d: %s", r.Status, msg)
	}
	return fmt.Errorf("forge answered %d", r.Status)
}

func failed(status int, format string, args ...any) Result {
	return Result{Outcome: OutcomeFailed, Status: status, Err: fmt.Errorf(format, args...)}
}

func applied(status int) Result { return Result{Outcome: OutcomeApplied, Status: status} }
