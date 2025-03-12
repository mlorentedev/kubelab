package api

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// LeadMagnetHandler maneja las solicitudes para procesar lead magnet (suscripción + envío de recurso)
func LeadMagnetHandler(c *gin.Context) {
	var request struct {
		Email      string `json:"email" binding:"required"`
		ResourceID string `json:"resourceId" binding:"required"`
		FileID     string `json:"fileId" binding:"required"`
		Tags       string `json:"tags"`
	}

	if err := c.ShouldBindJSON(&request); err != nil {
		logger.LogFunction("error", "Error in lead magnet endpoint", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{
			"success": false,
			"message": "Datos incompletos para completar la operación.",
		})
		return
	}

	// Validar email
	if !services.IsValidEmailFormat(request.Email) {
		c.JSON(http.StatusBadRequest, gin.H{
			"success": false,
			"message": "Correo electrónico inválido.",
		})
		return
	}

	// Procesar tags
	var tags []string
	if request.Tags != "" {
		tags = strings.Split(request.Tags, ",")
	}

	// Añadir tag específico del recurso
	resourceTag := "resource-" + request.ResourceID
	tags = append(tags, resourceTag)

	// Procesar suscripción
	subscriptionResult, err := services.ProcessSubscription(
		request.Email,
		string(models.SubscriptionSourceLeadMagnet),
		tags,
	)

	if err != nil {
		logger.LogFunction("error", "Error processing subscription for lead magnet", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": "Error interno del servidor.",
		})
		return
	}

	if !subscriptionResult.Success {
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": subscriptionResult.Message,
		})
		return
	}

	// Si la suscripción fue exitosa, programar el envío del email con recurso
	go func() {
		err := services.ScheduleResourceEmail(services.ResourceEmailScheduleOptions{
			Email:        request.Email,
			ResourceID:   request.ResourceID,
			FileID:       request.FileID,
			DelayMinutes: 1,
		})
		if err != nil {
			logger.LogFunction("error", "Error scheduling resource email", err.Error())
		}
	}()

	logger.LogFunction("info", "Lead magnet processed successfully", map[string]string{
		"email":      request.Email,
		"resourceId": request.ResourceID,
	})

	// Devolver respuesta
	c.JSON(http.StatusOK, gin.H{
		"success": true,
		"message": "Recurso enviado correctamente.",
	})
}
