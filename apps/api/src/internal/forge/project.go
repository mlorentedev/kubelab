package forge

import (
	"context"
	"encoding/json"
	"log"
	"time"
)

// ProjectPeriod keeps a webhook well inside the spec's 60-second bound.
const ProjectPeriod = 10 * time.Second

const projectBatch = 50

// EventLog is the projector's view of the store.
type EventLog interface {
	Pending(ctx context.Context, limit int) ([]Event, error)
	// Project writes the item, when there is one, and marks the delivery projected
	// in one transaction, so a crash between the two cannot project it twice.
	Project(ctx context.Context, e Event, item *Item) error
}

type webhookBody struct {
	Repository struct {
		Name  string `json:"name"`
		Owner struct {
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
	if raw == nil || body.Repository.Name == "" || body.Repository.Owner.Login == "" {
		return nil, nil
	}
	src := Source{Forge: e.Forge, Owner: body.Repository.Owner.Login, Repo: body.Repository.Name}
	item := raw.neutral(src)
	item.Kind = kind
	return &item, nil
}

// Projector turns stored deliveries into items.
type Projector struct{ Log EventLog }

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
			log.Printf("forge projection: %s delivery %s unreadable: %v", e.Forge, e.DeliveryID, err)
		}
		// One delivery the store refuses must not hold back the ones behind it.
		if err := p.Log.Project(ctx, e, item); err != nil {
			log.Printf("forge projection: %s delivery %s: %v", e.Forge, e.DeliveryID, err)
		}
	}
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
