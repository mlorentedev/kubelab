package forge

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"strings"
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
//
// Sources is what the reconcile reads. A delivery about any other repository is
// answered 204 and never written: the hook's scope lives on the forge, and a
// widened App installation or a mistyped scope must not reach the console's
// database (ADR-066 A2). No sources means nothing is stored.
type Receiver struct {
	Secrets map[string]string
	Sources []Source
	Store   EventStore
}

// declares reports whether the delivery's repository is one the reconcile reads.
// Forges treat owner and repository names without case, so the match does too.
func (rc *Receiver) declares(forgeName string, payload []byte) bool {
	var body webhookBody
	if json.Unmarshal(payload, &body) != nil {
		return false
	}
	owner, repo := body.Repository.Owner.Login, body.Repository.Name
	for _, s := range rc.Sources {
		if s.Forge == forgeName && strings.EqualFold(s.Owner, owner) && strings.EqualFold(s.Repo, repo) {
			return true
		}
	}
	return false
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
	if !rc.declares(forgeName, payload) {
		return http.StatusNoContent
	}
	stored := Event{Forge: forgeName, DeliveryID: delivery, Type: event, Payload: payload}
	if err := rc.Store.StoreEvent(ctx, stored); err != nil {
		// A 5xx makes the delivery show as failed, so it can be redelivered. The log
		// tells a missing table from a passing outage; the forge sees neither.
		log.Printf("forge webhook: store %s delivery %s: %v", forgeName, delivery, err)
		return http.StatusServiceUnavailable
	}
	return http.StatusAccepted
}
