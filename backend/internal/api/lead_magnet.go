package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// LeadMagnetHandler handles requests to process lead magnets (subscription + resource delivery)
func LeadMagnetHandler(c *gin.Context) {
	var request models.ResourceRequest
	var response models.ResourceResult

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

	logger.LogFunction("info", constants.Messages.Backend.Info["RequestProcessing"], request)

	// Validate email format
	if request.Email == "" || !services.IsValidEmailFormat(request.Email) {
		logger.LogFunction("error", constants.Messages.Backend.Error["InvalidEmail"], request.Email)
		setResponse(http.StatusBadRequest, false, constants.Messages.Frontend.Errors["InvalidEmail"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Process tags
	var tags []string
	if len(request.Tags) > 0 {
		tags = request.Tags
	}

	// Add resource-specific tag
	resourceTag := "resource-" + request.ResourceID
	tags = append(tags, resourceTag)

	// Process the subscription
	logger.LogFunction("info", constants.Messages.Backend.Info["SubscriptionProcessing"], map[string]interface{}{
		"email":      request.Email,
		"resourceId": request.ResourceID,
		"tags":       tags,
	})

	result, err := services.ProcessSubscription(request.Email, string(models.SubscriptionSourceLeadMagnet), tags)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["SubscriptionError"], err.Error())
		setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["ServerError"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Handle subscription result
	if result.AlreadySubscribed {
		// Schedule resource email for existing subscriber
		logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberExists"], map[string]string{
			"email":        request.Email,
			"subscriberId": result.SubscriberID,
		})

		err := services.ScheduleResourceEmail(models.ResourceEmailScheduleOptions{
			Email:        request.Email,
			ResourceID:   request.ResourceID,
			FileID:       request.FileID,
			DelayMinutes: 1,
		})

		if err != nil {
			logger.LogFunction("error", constants.Messages.Backend.Error["ServerError"], err.Error())
			setResponse(http.StatusInternalServerError, false, constants.Messages.Frontend.Errors["ServerError"])
			c.String(response.HttpCode, response.Message)
			return
		}

		logger.LogFunction("info", constants.Messages.Backend.Info["DelayedEmailScheduled"], map[string]string{
			"email":      request.Email,
			"resourceId": request.ResourceID,
		})
	} else {
		// For new subscribers, resource email is handled within ProcessSubscription
		logger.LogFunction("info", constants.Messages.Backend.Info["NewSubscriber"], map[string]string{
			"email":        request.Email,
			"subscriberId": result.SubscriberID,
		})
	}

	// Success response
	logger.LogFunction("info", constants.Messages.Backend.Info["ResourceSent"], map[string]string{
		"email":      request.Email,
		"resourceId": request.ResourceID,
	})

	setResponse(http.StatusCreated, true, constants.Messages.Frontend.Success["ResourceSent"])
	c.Header("HX-Redirect", constants.URLs.SuccessPages.Resource)
	c.String(response.HttpCode, response.Message)
}
