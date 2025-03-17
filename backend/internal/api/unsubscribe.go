package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// UnsubscribeHandler handles newsletter unsubscription requests
func UnsubscribeHandler(c *gin.Context) {
	var request models.UnsubscriptionRequest
	var response models.UnsubscriptionResult

	// Helper function to set the common response attributes
	setResponse := func(httpCode int, success bool, message string) {
		response.HttpCode = httpCode
		response.Success = success
		response.Message = message
	}

	// Bind form data
	if err := c.ShouldBind(&request); err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["IncompleteData"], err.Error())
		setResponse(http.StatusBadRequest, false, constants.Messages.Frontend.Errors["IncompleteData"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Validate email format
	if request.Email == "" || !services.IsValidEmailFormat(request.Email) {
		logger.LogFunction("error", constants.Messages.Backend.Error["InvalidEmail"], request.Email)
		setResponse(http.StatusBadRequest, false, constants.Messages.Frontend.Errors["InvalidEmail"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Check if the subscriber exists
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["CheckSubscriberError"], err.Error())
		setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["ServerError"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Handle based on subscriber existence
	if existingSubscriber.Success && existingSubscriber.Subscriber != nil {
		// Subscriber exists, proceed with unsubscribe
		logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberExists"], map[string]string{
			"email":  request.Email,
			"id":     existingSubscriber.Subscriber.ID,
			"action": "unsubscribe",
		})

		result, err := services.UnsubscribeUser(request.Email)
		if err != nil {
			logger.LogFunction("error", constants.Messages.Backend.Error["UnsubscribeError"], err.Error())
			setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["ServerError"])
			c.String(response.HttpCode, response.Message)
			return
		}

		if result.Success {
			logger.LogFunction("info", constants.Messages.Backend.Info["UserUnsubscribed"], map[string]string{
				"email": request.Email,
				"id":    existingSubscriber.Subscriber.ID,
			})

			setResponse(http.StatusOK, true, constants.Messages.Frontend.Success["Unsubscription"])
			c.Header("HX-Redirect", constants.URLs.SuccessPages.Unsubscribe)
			c.String(response.HttpCode, response.Message)
		} else {
			logger.LogFunction("error", constants.Messages.Backend.Error["UnsubscribeError"], result.Message)
			setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["UnsubscriptionError"])
			c.String(response.HttpCode, response.Message)
		}
	} else {
		// Email not subscribed
		logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberNotFound"], map[string]string{
			"email":  request.Email,
			"action": "unsubscribe",
		})

		setResponse(http.StatusConflict, false, constants.Messages.Frontend.Errors["EmailNotSubscribed"])
		c.String(response.HttpCode, response.Message)
		return
	}
}
