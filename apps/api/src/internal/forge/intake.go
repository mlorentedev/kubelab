package forge

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// The write path's front door (CONSOLE-004 AC2, ADR-066 W1 and W21): everything a route asks of a
// request before it becomes an outbox row, so the console's routes and the machine create judge
// a write by one set of rules and cannot drift apart. The routes translate the answers to HTTP.

// MachineActor is the actor of a write made with the machine token. A Remote-User equal to it is
// refused by the console's routes, so the two namespaces cannot collide in
// UNIQUE (actor, idempotency_key): an operator could otherwise replay a machine's key and be
// handed its stored response.
const MachineActor = "machine"

// FailedShownFor is how long a failed write stays in the queue's `writes`, counted from the last
// forge call made for it (its latest audit row), not from when it was queued.
const FailedShownFor = 24 * time.Hour

// The classes of refusal an Intake returns. A route maps ErrInvalid to 400, ErrRefused and
// ErrKeyReuse to 422, ErrUnavailable and ErrNoWriter to 503.
var (
	// ErrInvalid is a request that is malformed: a missing or unusable key, a field out of shape.
	ErrInvalid = errors.New("invalid request")
	// ErrRefused is a well-formed request the platform does not perform: a target outside the
	// declared sources, a pull request closed through an issue route, a label outside the
	// workflow's two families, or text that carries the write marker.
	ErrRefused = errors.New("request refused")
	// ErrUnavailable is a write the environment cannot take now: the gate is off, or the
	// declaration or the read model cannot be read.
	ErrUnavailable = errors.New("writes unavailable")
)

// The bounds on what a write carries. The forges' own limits are wider; these keep the outbox and
// the audit small and a request cheap to judge.
const (
	maxKeyLen   = 255
	maxTitleLen = 256
	maxBodyLen  = 60000
	maxLabelLen = 100
	maxLoginLen = 100
)

var (
	loginRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)
	nameRe  = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)
)

// LabelFamilies are the only labels a write may add or remove (the spec's "status:* or
// priority:* label"). Every other label, area: among them, is set on the forge.
var LabelFamilies = []string{"status:", "priority:"}

// Enqueuer keeps an accepted write.
type Enqueuer interface {
	Enqueue(ctx context.Context, e Enqueue) (Receipt, error)
}

// KindReader says what the read model holds at a number: an issue or a pull request. ok is false
// for a number it has not met.
type KindReader interface {
	ItemKind(ctx context.Context, s Source, number int) (kind Kind, ok bool, err error)
}

// Request is one write as a route read it: the actor and key from its headers, the target and the
// fields from its path and body. Nothing in it is trusted until Accept has judged it.
type Request struct {
	Actor  string
	Key    string
	Action Action
	Source Source
	Number int // 0 for a create
	Title  string
	Body   string
	Label  string
	Login  string
}

// Intake judges a write and puts it in the outbox.
type Intake struct {
	Store Enqueuer
	Kinds KindReader
	// Writers is the gate (W14): with none, or none for the target's forge, a write is refused
	// with ErrUnavailable and nothing is enqueued.
	Writers map[string]Writer
	// Sources is infra.forge.sources, wildcards resolved: the only repositories a write may name.
	Sources func() ([]Source, error)
}

// Accept judges req and enqueues it. A replay of an earlier request by the same actor and key
// returns that request's receipt and writes nothing.
//
// The order is the contract: the gate first (so a closed environment answers 503 whatever the
// request says), then the key and the shape of the request, then what the platform allows, and
// only then the database.
func (in *Intake) Accept(ctx context.Context, req Request) (Receipt, error) {
	if in == nil || len(in.Writers) == 0 {
		return Receipt{}, fmt.Errorf("%w: no forge accepts writes here", ErrUnavailable)
	}
	if err := validKey(req.Key); err != nil {
		return Receipt{}, err
	}
	if strings.TrimSpace(req.Actor) == "" {
		return Receipt{}, fmt.Errorf("%w: no actor", ErrInvalid)
	}
	if err := validShape(req); err != nil {
		return Receipt{}, err
	}
	if _, err := WriterFor(in.Writers, req.Source.Forge); err != nil {
		return Receipt{}, fmt.Errorf("%w: %s accepts no writes here", ErrUnavailable, req.Source.Forge)
	}
	target, err := in.declared(req.Source)
	if err != nil {
		return Receipt{}, err
	}
	req.Source = target
	req.Title = strings.TrimSpace(req.Title)
	if err := validAllowed(req); err != nil {
		return Receipt{}, err
	}
	if req.Action == ActionClose || req.Action == ActionReopen {
		kind, ok, err := in.Kinds.ItemKind(ctx, req.Source, req.Number)
		if err != nil {
			return Receipt{}, fmt.Errorf("%w: the read model: %v", ErrUnavailable, err)
		}
		if ok && kind == KindPull {
			return Receipt{}, fmt.Errorf("%w: %s #%d is a pull request, and a pull request is closed on its forge", ErrRefused, req.Source, req.Number)
		}
	}
	receipt, err := in.Store.Enqueue(ctx, Enqueue{
		Actor: req.Actor, Key: req.Key, Hash: HashOf(req), Action: req.Action, Source: req.Source, Number: req.Number,
		Payload: Payload{Title: req.Title, Body: req.Body, Label: req.Label, Login: req.Login},
	})
	if err != nil && !errors.Is(err, ErrKeyReuse) {
		return Receipt{}, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	return receipt, err
}

// declared returns the declared source s names, as the declaration spells it, or ErrRefused.
// Forge, owner and repository are compared without case, as the forges compare them.
func (in *Intake) declared(s Source) (Source, error) {
	if in.Sources == nil {
		return Source{}, fmt.Errorf("%w: the forge sources are not declared", ErrUnavailable)
	}
	list, err := in.Sources()
	if err != nil {
		return Source{}, fmt.Errorf("%w: the forge sources: %v", ErrUnavailable, err)
	}
	for _, d := range list {
		if strings.EqualFold(d.Forge, s.Forge) && strings.EqualFold(d.Owner, s.Owner) && strings.EqualFold(d.Repo, s.Repo) {
			return d, nil
		}
	}
	return Source{}, fmt.Errorf("%w: %s is not one of the declared forge sources", ErrRefused, s)
}

func validKey(key string) error {
	if key == "" {
		return fmt.Errorf("%w: the Idempotency-Key header is required", ErrInvalid)
	}
	if len(key) > maxKeyLen {
		return fmt.Errorf("%w: the Idempotency-Key is longer than %d bytes", ErrInvalid, maxKeyLen)
	}
	for i := 0; i < len(key); i++ {
		if key[i] <= ' ' || key[i] > '~' {
			return fmt.Errorf("%w: the Idempotency-Key must be printable ASCII with no spaces", ErrInvalid)
		}
	}
	return nil
}

// validShape checks the request is well formed, whatever the platform allows.
func validShape(r Request) error {
	s := r.Source
	if (s.Forge != "github" && s.Forge != "gitea") || !nameRe.MatchString(s.Owner) || !nameRe.MatchString(s.Repo) || s.Wildcard() {
		return fmt.Errorf("%w: the source must be <forge>:<owner>/<repo>, forge github or gitea", ErrInvalid)
	}
	switch r.Action {
	case ActionCreate:
		if r.Number != 0 {
			return fmt.Errorf("%w: a create names no issue number", ErrInvalid)
		}
		title := strings.TrimSpace(r.Title)
		if title == "" || utf8.RuneCountInString(title) > maxTitleLen || strings.ContainsAny(title, "\r\n") {
			return fmt.Errorf("%w: the title must be one line of 1 to %d characters", ErrInvalid, maxTitleLen)
		}
		if len(r.Body) > maxBodyLen || !utf8.ValidString(r.Body) || !utf8.ValidString(r.Title) {
			return fmt.Errorf("%w: the body is longer than %d bytes or not UTF-8", ErrInvalid, maxBodyLen)
		}
		return nil
	case ActionAddLabel, ActionRemoveLabel:
		if r.Label == "" || len(r.Label) > maxLabelLen || strings.ContainsFunc(r.Label, func(c rune) bool { return c < ' ' || c == 0x7f }) {
			return fmt.Errorf("%w: the label must be 1 to %d printable characters", ErrInvalid, maxLabelLen)
		}
	case ActionAddAssignee, ActionRemoveAssignee:
		if len(r.Login) > maxLoginLen || !loginRe.MatchString(r.Login) {
			return fmt.Errorf("%w: the login is not one a forge allows", ErrInvalid)
		}
	case ActionClose, ActionReopen:
	default:
		return fmt.Errorf("%w: %q is not a write", ErrInvalid, r.Action)
	}
	if r.Number <= 0 || r.Number > 1<<31-1 {
		return fmt.Errorf("%w: the issue number must be a positive integer", ErrInvalid)
	}
	return nil
}

// validAllowed checks what the platform will do with a well-formed request.
func validAllowed(r Request) error {
	switch r.Action {
	case ActionCreate:
		// The marker is how a create is found again after a lost answer (W4, W11). Text that
		// carries it could make the search adopt another issue as this one's.
		if hasMarker(r.Title) || hasMarker(r.Body) {
			return fmt.Errorf("%w: the text carries the write marker", ErrRefused)
		}
	case ActionAddLabel, ActionRemoveLabel:
		for _, family := range LabelFamilies {
			if strings.HasPrefix(r.Label, family) && len(r.Label) > len(family) {
				return nil
			}
		}
		return fmt.Errorf("%w: a write sets only %s labels", ErrRefused, strings.Join(LabelFamilies, " or "))
	}
	return nil
}

func hasMarker(s string) bool {
	return strings.Contains(strings.ToLower(s), "kubelab-write:")
}

// HashOf is the digest of the whole request that W1 stores: the action, the target (forge, owner,
// repository, issue number) and every field, so one key reused on another issue is a different
// request and is refused, not replayed. The target is hashed as the declaration spells it, so a
// request that writes it in another case is the same request.
func HashOf(r Request) string {
	b, _ := json.Marshal(struct {
		Action string `json:"a"`
		Forge  string `json:"f"`
		Owner  string `json:"o"`
		Repo   string `json:"r"`
		Number int    `json:"n"`
		Title  string `json:"t"`
		Body   string `json:"b"`
		Label  string `json:"l"`
		Login  string `json:"g"`
	}{string(r.Action), strings.ToLower(r.Source.Forge), strings.ToLower(r.Source.Owner), strings.ToLower(r.Source.Repo),
		r.Number, r.Title, r.Body, r.Label, r.Login})
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// WriteRow is a write the queue shows: one still owed, or one that failed recently.
type WriteRow struct {
	ID     int64
	Action Action
	Source Source
	Number int // 0 for a create the forge has not answered
	// Detail is the title of a create, the label or the login of the others. Never a body.
	Detail    string
	Status    string // pending (in flight included) or failed
	LastError string
	QueuedAt  time.Time
}

// WriteReader reads the writes the queue shows: every row pending or in flight, and every failed
// row whose latest audit row is not older than failedSince.
type WriteReader interface {
	Writes(ctx context.Context, failedSince time.Time) ([]WriteRow, error)
}
