package api

import (
	"context"
	"log"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// pgEvents adapts the store's function to the receiver's interface.
type pgEvents struct{ conf config.Postgres }

func (p pgEvents) StoreEvent(ctx context.Context, e forge.Event) error {
	return store.StoreEvent(ctx, p.conf, e.Forge, e.DeliveryID, e.Type, e.Payload)
}

// ForgeWebhookHandler answers a forge delivery with a status and no body.
func ForgeWebhookHandler(c *gin.Context) {
	conf, err := config.GetConfig()
	if err != nil {
		log.Printf("forge webhook: configuration unavailable")
		c.Status(503)
		return
	}
	// The reconcile's sources, so a delivery is kept only for a repository it reads.
	// A declaration that does not parse leaves none, and nothing is stored.
	sources, err := forge.ParseSources(conf.Forge.Sources)
	if err != nil {
		log.Printf("forge webhook: sources: %v", err)
	}
	rc := forge.Receiver{
		Secrets: map[string]string{"github": conf.Forge.GitHubWebhookSecret, "gitea": conf.Forge.GiteaWebhookSecret},
		Sources: sources,
		Store:   pgEvents{conf: conf.Postgres},
	}
	c.Status(rc.Handle(c.Request.Context(), c.Param("forge"), c.Request.Header, c.Request.Body))
}
