package api

import (
	"github.com/gin-gonic/gin"
)

// SetupRoutes configura todas las rutas de la API
func SetupRoutes(r *gin.Engine) {

	// Health check routes
	RegisterHealthCheckRoutes(r)

	// Grupo API
	api := r.Group("/api")
	{
		// Suscripción
		api.POST("/subscribe", SubscribeHandler)

		// Cancelación de suscripción
		api.POST("/unsubscribe", UnsubscribeHandler)

		// Lead magnet
		api.POST("/lead-magnet", LeadMagnetHandler)

		// Email con recurso
		api.POST("/resource-email", ResourceEmailHandler)
	}
}
