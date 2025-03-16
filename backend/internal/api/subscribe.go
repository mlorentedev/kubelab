package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

func SubscribeHandler(c *gin.Context) {
	var request models.SubscriptionRequest
	var response models.SubscriptionResult

	// Helper function to set the common response attributes
	setResponse := func(httpCode int, success bool, message string, alreadySubscribed bool, subscriberID string) {
		response.HttpCode = httpCode
		response.Success = success
		response.Message = message
		response.AlreadySubscribed = alreadySubscribed
		response.SubscriberID = subscriberID
	}

	// Bind form data
	if err := c.ShouldBind(&request); err != nil {
		logger.LogFunction("error", constants.ServerMessages.Errors["IncompletData"], err.Error())
		setResponse(http.StatusBadRequest, false, constants.FrontendMessages.Errors["IncompletData"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Validate email format
	if request.Email == "" || !services.IsValidEmailFormat(request.Email) {
		setResponse(http.StatusBadRequest, false, constants.FrontendMessages.Errors["InvalidEmail"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Set default value for utmSource if empty
	if request.UtmSource == "" {
		request.UtmSource = string(models.SubscriptionSourceLandingPage)
	}

	// Check if the subscriber already exists
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		setResponse(http.StatusInternalServerError, false, constants.FrontendMessages.Errors["ServerError"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	if existingSubscriber.Success && existingSubscriber.Subscriber != nil {
		setResponse(http.StatusConflict, false, constants.FrontendMessages.Errors["SubscriptionError"], true, existingSubscriber.Subscriber.ID)
		c.String(response.HttpCode, response.Message)
		return
	}

	// Process the new subscription
	result, err := services.ProcessSubscription(request.Email, request.UtmSource, request.Tags)
	if err != nil {
		setResponse(http.StatusInternalServerError, false, constants.FrontendMessages.Errors["ServerError"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Successful subscription
	setResponse(http.StatusCreated, true, constants.FrontendMessages.Success["SubscriptionNew"], false, result.SubscriberID)
	c.Header("HX-Redirect", constants.URLs.SuccessPages.Subscription)
	c.String(response.HttpCode, response.Message)
}
