package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// SubscribeHandler maneja las solicitudes para suscribir usuarios
func SubscribeHandler(c *gin.Context) {
	var request models.SubscriptionRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		logger.LogFunction("error", "Error in subscription endpoint", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{
			"message": "Correo electrónico inválido.",
		})
		return
	}

	// Validar email
	if !services.IsValidEmailFormat(request.Email) {
		c.JSON(http.StatusBadRequest, gin.H{
			"message": "Correo electrónico inválido.",
		})
		return
	}

	// Usar valor por defecto para utmSource si no está presente
	if request.UtmSource == "" {
		request.UtmSource = string(models.SubscriptionSourceLandingPage)
	}

	// Procesar suscripción
	result, err := services.ProcessSubscription(request.Email, request.Tags, request.UtmSource)
	if err != nil {
		logger.LogFunction("error", "Error processing subscription", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{
			"message": "Error interno del servidor.",
		})
		return
	}

	// Devolver respuesta
	c.JSON(http.StatusOK, gin.H{
		"message":           result.Message,
		"alreadySubscribed": result.AlreadySubscribed,
	})
}
