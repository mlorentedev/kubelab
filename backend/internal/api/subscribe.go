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

	var response models.SubscriptionResult

	// Intentamos hacer bind de los datos del formulario (x-www-form-urlencoded)
	if err := c.ShouldBind(&request); err != nil {
		logger.LogFunction("error", "Error al hacer bind de la solicitud", err.Error())
		response.Success = false
		response.Message = "Error al procesar la solicitud"
		response.AlreadySubscribed = false
		response.SubscriberID = ""
		c.JSON(http.StatusBadRequest, response)
		return
	}

	// Validamos el formato del correo electrónico
	if !services.IsValidEmailFormat(request.Email) {
		response.Success = false
		response.Message = "Correo electrónico inválido"
		response.AlreadySubscribed = false
		response.SubscriberID = ""
		c.JSON(http.StatusOK, response)
		return
	}

	// Asignamos un valor por defecto para utmSource si no se ha proporcionado
	if request.UtmSource == "" {
		request.UtmSource = string(models.SubscriptionSourceLandingPage)
	}

	// Comprobamos si el suscriptor ya existe
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		response.Success = false
		response.Message = "Error interno del servidor"
		response.AlreadySubscribed = false
		response.SubscriberID = ""
		c.JSON(http.StatusInternalServerError, response)
		return
	}

	// Si el suscriptor ya existe, devolvemos un mensaje específico
	if existingSubscriber.Success && existingSubscriber.Subscriber != nil {
		response.Success = true
		response.Message = "Ya estás suscrito"
		response.AlreadySubscribed = true
		response.SubscriberID = existingSubscriber.Subscriber.ID
		c.JSON(http.StatusConflict, response)
		return
	}

	// Procesamos la nueva suscripción
	result, err := services.ProcessSubscription(request.Email, request.UtmSource, request.Tags)
	if err != nil {
		response.Success = false
		response.Message = "Error al procesar la suscripción"
		response.AlreadySubscribed = false
		response.SubscriberID = ""
		c.JSON(http.StatusInternalServerError, response)
		return
	}

	// Devolvemos la respuesta
	response.Success = true
	response.Message = "Suscripción exitosa"
	response.AlreadySubscribed = false
	response.SubscriberID = result.SubscriberID
	c.Header("HX-Redirect", "/subscribe-success")
	c.JSON(http.StatusCreated, response)
}
