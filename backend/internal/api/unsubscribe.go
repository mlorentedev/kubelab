package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// UnsubscribeHandler maneja las solicitudes de cancelación de suscripción
func UnsubscribeHandler(c *gin.Context) {
	var request models.UnsubscriptionRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		logger.LogFunction("error", "Error in unsubscribe endpoint: invalid request", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{
			"success": false,
			"message": "Correo electrónico inválido.",
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

	// Procesar cancelación
	result, err := services.UnsubscribeUser(request.Email)
	if err != nil {
		logger.LogFunction("error", "Error in unsubscribe endpoint", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": "Error interno del servidor.",
		})
		return
	}

	// Devolver respuesta
	c.JSON(http.StatusOK, gin.H{
		"success": result.Success,
		"message": result.Message,
	})
}

// UnsubscribeGetHandler maneja solicitudes GET para cancelar suscripción con redirección
func UnsubscribeGetHandler(c *gin.Context) {
	email := c.Query("email")

	// Validar entrada
	if email == "" || !services.IsValidEmailFormat(email) {
		c.Redirect(http.StatusFound, "/404")
		return
	}

	// Procesar cancelación
	result, err := services.UnsubscribeUser(email)
	if err != nil {
		logger.LogFunction("error", "Error in GET unsubscribe endpoint", err.Error())
		c.Redirect(http.StatusFound, "/404")
		return
	}

	// Redireccionar según resultado
	if result.Success {
		c.Redirect(http.StatusFound, "/unsubscribe-success")
	} else {
		c.Redirect(http.StatusFound, "/404")
	}
}
