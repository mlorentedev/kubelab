package forge

import (
	"context"
	"encoding/json"
	"log"
	"log/slog"
	"time"
)

// ProjectPeriod keeps a webhook well inside the spec's 60-second bound.
const ProjectPeriod = 10 * time.Second

const projectBatch = 50

// BacklogPeriod bounds how often the projector writes its backlog line. It runs each
// ProjectPeriod, and a line per run would outnumber everything else the API writes.
const BacklogPeriod = time.Minute

// EventLog is the projector's view of the store.
type EventLog interface {
	Pending(ctx context.Context, limit int) ([]Event, error)
	// Backlog counts every delivery not yet projected and returns the oldest one's
	// receipt time, zero when there is none. Pending is a batch and cannot count.
	Backlog(ctx context.Context) (depth int, oldest time.Time, err error)
	// Project writes the item, when there is one, and marks the delivery projected
	// in one transaction, so a crash between the two cannot project it twice.
	Project(ctx context.Context, e Event, item *Item) error
}

type webhookBody struct {
	Action     string `json:"action"`
	Repository struct {
		Name     string `json:"name"`
		Fork     bool   `json:"fork"`
		Archived bool   `json:"archived"`
		Owner    struct {
			Login string `json:"login"`
		} `json:"owner"`
	} `json:"repository"`
	Issue       *restItem `json:"issue"`
	PullRequest *restItem `json:"pull_request"`
}

// ItemFromEvent reads the item a delivery describes. An event about anything else
// returns nil, which is an answer: it is marked projected and never read again.
func ItemFromEvent(e Event) (*Item, error) {
	var body webhookBody
	if err := json.Unmarshal(e.Payload, &body); err != nil {
		return nil, err
	}
	var raw *restItem
	kind := KindIssue
	switch e.Type {
	case "issues":
		raw = body.Issue
	case "pull_request":
		raw, kind = body.PullRequest, KindPull
	}
	// A deleted item's delivery carries the full item; writing it would bring it back.
	if raw == nil || body.Action == "deleted" || body.Repository.Name == "" || body.Repository.Owner.Login == "" {
		return nil, nil
	}
	src := Source{Forge: e.Forge, Owner: body.Repository.Owner.Login, Repo: body.Repository.Name}
	item := raw.neutral(src)
	item.Kind = kind
	return &item, nil
}

// Projector turns stored deliveries into items.
type Projector struct {
	Log    EventLog
	Events *slog.Logger     // nil writes JSON lines to stderr (events.go)
	Now    func() time.Time // nil is time.Now

	lastBacklog time.Time
}

// backlog writes the backlog line at most once per BacklogPeriod, an empty one included:
// a line that only appeared with a backlog would make an idle queue and a stopped
// projector look the same. A count that fails is logged and costs no projection.
func (p *Projector) backlog(ctx context.Context) {
	now := time.Now()
	if p.Now != nil {
		now = p.Now()
	}
	if !p.lastBacklog.IsZero() && now.Sub(p.lastBacklog) < BacklogPeriod {
		return
	}
	// Before the count, so a count that keeps failing is retried, and logged, once per
	// period too, not on every run.
	p.lastBacklog = now
	depth, oldest, err := p.Log.Backlog(ctx)
	if err != nil {
		log.Printf("forge projection backlog: %v", err)
		return
	}
	age := 0.0
	if !oldest.IsZero() {
		age = now.Sub(oldest).Seconds()
	}
	emit(p.Events, slog.LevelInfo, EventProjectionBacklog,
		slog.Int("depth", depth), slog.Float64("oldest_age_seconds", age))
}

// Once projects one batch. A delivery that cannot be read is marked projected and
// logged: leaving it pending would retry it forever, and the reconcile covers the item.
func (p *Projector) Once(ctx context.Context) error {
	events, err := p.Log.Pending(ctx, projectBatch)
	if err != nil {
		return err
	}
	for _, e := range events {
		item, err := ItemFromEvent(e)
		if err != nil {
			webhookFailure(p.Events, e.Forge, e.DeliveryID, "unreadable", err)
		}
		if err := p.Log.Project(ctx, e, item); err != nil {
			webhookFailure(p.Events, e.Forge, e.DeliveryID, "projection", err)
			// Pending is oldest first, so a delivery the store always refuses would end up
			// filling every batch. Mark it without its item: the reconcile covers the item,
			// and if the database is down this fails too and the delivery stays pending.
			if err := p.Log.Project(ctx, e, nil); err != nil {
				return err
			}
		}
	}
	// After the batch, so the line reports what this run left behind.
	p.backlog(ctx)
	return nil
}

// Run projects every period until ctx ends.
func (p *Projector) Run(ctx context.Context, period time.Duration) {
	ticker := time.NewTicker(period)
	defer ticker.Stop()
	for {
		if err := p.Once(ctx); err != nil {
			log.Printf("forge projection: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
