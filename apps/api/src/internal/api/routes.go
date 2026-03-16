package api

import (
	"github.com/gin-gonic/gin"
)

// SetupRoutes configures all API routes
func SetupRoutes(r *gin.Engine) {

	// Health check routes
	RegisterHealthCheckRoutes(r)

	// API Group
	api := r.Group("/api")
	{
		// Subscription
		api.POST("/subscribe", SubscribeHandler)

		// Subscription cancellation
		api.POST("/unsubscribe", UnsubscribeHandler)

		// Lead magnet
		api.POST("/lead-magnet", LeadMagnetHandler)

	}
}
