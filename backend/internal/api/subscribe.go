package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

func SubscribeHandler(c *gin.Context) {
	var request models.SubscriptionRequest

	if err := c.ShouldBindJSON(&request); err != nil {
		logger.LogFunction("error", "Error in subscription endpoint", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{
			"success": false,
			"message": "Datos inválidos. Asegúrate de incluir un correo electrónico válido.",
		})
		return
	}

	// Validate email
	if !services.IsValidEmailFormat(request.Email) {
		c.JSON(http.StatusBadRequest, gin.H{
			"success": false,
			"message": "Correo electrónico inválido.",
		})
		return
	}

	// Use default value for utmSource if not present
	if request.UtmSource == "" {
		request.UtmSource = string(models.SubscriptionSourceLandingPage)
	}

	// Check if subscriber already exists
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		logger.LogFunction("error", "Error checking subscriber", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": "Error interno del servidor.",
		})
		return
	}

	// If subscriber exists, return a specific message
	if existingSubscriber.Success && existingSubscriber.Subscriber != nil {
		c.JSON(http.StatusConflict, gin.H{
			"success": false,
			"message": "Este correo ya está suscrito.",
		})
		return
	}

	// Process new subscription
	result, err := services.ProcessSubscription(request.Email, request.UtmSource, request.Tags)
	if err != nil {
		logger.LogFunction("error", "Error processing subscription", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": "Error interno del servidor.",
		})
		return
	}

	// Return response
	c.JSON(http.StatusOK, gin.H{
		"success":           true,
		"message":           result.Message,
		"alreadySubscribed": result.AlreadySubscribed,
	})
}
