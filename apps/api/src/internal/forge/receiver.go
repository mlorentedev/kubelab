package forge

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
)

// maxWebhookBody is GitHub's own cap on a delivery: 25 MiB.
const maxWebhookBody = 25 << 20

// Event is one verified webhook delivery, before any projection.
type Event struct {
	Forge      string
	DeliveryID string
	Type       string
	Payload    []byte
}

// EventStore keeps a delivery durably. Storing the same delivery twice is a
// success that changes nothing: a forge redelivers, and that must not fail.
type EventStore interface {
	StoreEvent(ctx context.Context, e Event) error
}

// webhookHeaders names what each forge sends.
var webhookHeaders = map[string]struct{ Signature, Delivery, Event string }{
	"github": {"X-Hub-Signature-256", "X-GitHub-Delivery", "X-GitHub-Event"},
	"gitea":  {"X-Gitea-Signature", "X-Gitea-Delivery", "X-Gitea-Event"},
}

// Receiver stores a verified delivery before anything reads it, so a failed
// projection replays from the store and not from the forge. Secrets holds one
// secret per forge; a forge with none rejects everything (VerifySignature).
type Receiver struct {
	Secrets map[string]string
	Store   EventStore
}

// Handle returns the HTTP status for one delivery. The signature is checked
// before the store is reached, so an unsigned caller cannot spend a write.
func (rc *Receiver) Handle(ctx context.Context, forgeName string, header http.Header, body io.Reader) int {
	names, known := webhookHeaders[forgeName]
	if !known {
		return http.StatusNotFound
	}
	payload, err := io.ReadAll(io.LimitReader(body, maxWebhookBody+1))
	if err != nil {
		return http.StatusBadRequest
	}
	if len(payload) > maxWebhookBody {
		return http.StatusRequestEntityTooLarge
	}
	if !VerifySignature(forgeName, rc.Secrets[forgeName], header.Get(names.Signature), payload) {
		return http.StatusUnauthorized
	}
	delivery, event := header.Get(names.Delivery), header.Get(names.Event)
	if delivery == "" || event == "" || !json.Valid(payload) {
		return http.StatusBadRequest
	}
	stored := Event{Forge: forgeName, DeliveryID: delivery, Type: event, Payload: payload}
	if err := rc.Store.StoreEvent(ctx, stored); err != nil {
		// A 5xx makes the delivery show as failed, so it can be redelivered.
		return http.StatusServiceUnavailable
	}
	return http.StatusAccepted
}
