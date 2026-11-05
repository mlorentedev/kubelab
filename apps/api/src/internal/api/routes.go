package api

import (
	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/console"
)

// SetupRoutes configures all API routes
func SetupRoutes(r *gin.Engine) {

	// Health check routes
	RegisterHealthCheckRoutes(r)

	// Forge console: served only on its own host, which Authelia guards (CONSOLE-004)
	console.Register(r, console.Live, console.LiveDomain)

	// API Group
	api := r.Group("/api")
	{
		// Subscription
		api.POST("/subscribe", SubscribeHandler)

		// Subscription cancellation
		api.POST("/unsubscribe", UnsubscribeHandler)

		// Lead magnet
		api.POST("/lead-magnet", LeadMagnetHandler)

		// Forge webhooks: signed by the forge, so no session in front of them
		api.POST("/forge/webhooks/:forge", ForgeWebhookHandler)
	}
}
