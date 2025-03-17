package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// SubscribeHandler handles newsletter subscription requests
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
		logger.LogFunction("error", constants.Messages.Backend.Error["IncompleteData"], err.Error())
		setResponse(http.StatusBadRequest, false, constants.Messages.Frontend.Errors["IncompleteData"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Validate email format
	if request.Email == "" || !services.IsValidEmailFormat(request.Email) {
		logger.LogFunction("error", constants.Messages.Backend.Error["InvalidEmail"], request.Email)
		setResponse(http.StatusBadRequest, false, constants.Messages.Frontend.Errors["InvalidEmail"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Set default value for utmSource if empty
	if request.UtmSource == "" {
		request.UtmSource = string(models.SubscriptionSourceLandingPage)
		logger.LogFunction("info", "Using default UTM source", map[string]string{
			"email":     request.Email,
			"utmSource": request.UtmSource,
		})
	}

	// Check if the subscriber already exists
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["CheckSubscriberError"], err.Error())
		setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["ServerError"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	if existingSubscriber.Success && existingSubscriber.Subscriber != nil {
		logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberExists"], map[string]string{
			"email": request.Email,
			"id":    existingSubscriber.Subscriber.ID,
		})
		setResponse(http.StatusConflict, false, constants.Messages.Frontend.Errors["SubscriptionError"], true, existingSubscriber.Subscriber.ID)
		c.String(response.HttpCode, response.Message)
		return
	}

	// Process tags
	var tags []string
	if len(request.Tags) > 0 {
		tags = request.Tags
		logger.LogFunction("info", "Processing subscription with tags", map[string]interface{}{
			"email": request.Email,
			"tags":  tags,
		})
	}

	// Process the subscription
	result, err := services.ProcessSubscription(request.Email, request.UtmSource, tags)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["SubscriptionError"], err.Error())
		setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["ServerError"], false, "")
		c.String(response.HttpCode, response.Message)
		return
	}

	// Successful subscription
	logger.LogFunction("info", constants.Messages.Backend.Info["NewSubscriber"], map[string]string{
		"email": request.Email,
		"id":    result.SubscriberID,
	})

	setResponse(http.StatusCreated, true, constants.Messages.Frontend.Success["SubscriptionNew"], false, result.SubscriberID)
	c.Header("HX-Redirect", constants.URLs.SuccessPages.Subscription)
	c.String(response.HttpCode, response.Message)
}
