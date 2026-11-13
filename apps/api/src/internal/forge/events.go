package forge

import (
	"context"
	"log/slog"
	"os"
)

// The `event` field of each structured line (AC6). The runbook's LogQL selects on
// these names, so renaming one breaks a query nothing else would notice.
const (
	// EventSourceFreshness is one source after a read attempt: its as_of and age.
	EventSourceFreshness = "forge_source_freshness"
	// EventReconcileCycle is one pass over a set of sources, with its duration.
	EventReconcileCycle = "forge_reconcile_cycle"
	// EventWebhookFailure is a delivery refused or not projected, with its reason.
	EventWebhookFailure = "forge_webhook_failure"
	// EventProjectionBacklog is the deliveries stored and not yet projected: how many,
	// and the age of the oldest. Not the outbox: that is the outbound write queue (AC2).
	EventProjectionBacklog = "forge_projection_backlog"
)

// defaultEvents writes one JSON object per line to stderr, where the API's text log
// goes too. Loki reads a line as JSON with `| json`, and leaves the text lines alone.
var defaultEvents = slog.New(slog.NewJSONHandler(os.Stderr, nil))

// emit writes one event. A nil logger is the default one.
func emit(l *slog.Logger, level slog.Level, event string, attrs ...slog.Attr) {
	if l == nil {
		l = defaultEvents
	}
	l.LogAttrs(context.Background(), level, event, append([]slog.Attr{slog.String("event", event)}, attrs...)...)
}
