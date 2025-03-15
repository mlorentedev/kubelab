package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

func UnsubscribeHandler(c *gin.Context) {
	var request models.UnsubscriptionRequest
	var response models.UnsubscriptionResult

	// Helper function to set the common response attributes
	setResponse := func(httpCode int, success bool, message string) {
		response.HttpCode = httpCode
		response.Success = success
		response.Message = message
	}

	if err := c.ShouldBind(&request); err != nil {
		logger.LogFunction("error", "Error al hacer bind de la solicitud", err.Error())
		setResponse(http.StatusBadRequest, false, "Error al procesar la solicitud")
		c.String(response.HttpCode, response.Message)
		return
	}

	if request.Email == "" {
		setResponse(http.StatusBadRequest, false, "El correo electrónico es obligatorio")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Validar email
	if !services.IsValidEmailFormat(request.Email) {
		setResponse(http.StatusBadRequest, false, "Correo electrónico inválido")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Verificar si el suscriptor existe
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		setResponse(http.StatusInternalServerError, false, "Error interno del servidor")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Si el suscriptor no existe, devolver un mensaje específico
	if !existingSubscriber.Success || existingSubscriber.Subscriber == nil {
		setResponse(http.StatusNotFound, false, "Este correo no está en la lista")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Procesar cancelación
	result, err := services.UnsubscribeUser(request.Email)
	if err != nil {
		setResponse(http.StatusInternalServerError, false, "Error interno del servidor")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Successful unsubscription
	if result.Success {
		setResponse(http.StatusOK, true, "Desuscripción exitosa")
		c.Header("HX-Redirect", "/unsubscribe-success")
		c.String(response.HttpCode, response.Message)
	} else {
		setResponse(http.StatusInternalServerError, false, "Error al procesar la desuscripción")
		c.String(response.HttpCode, response.Message)
	}
}
