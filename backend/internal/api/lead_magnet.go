package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// LeadMagnetHandler maneja las solicitudes para procesar lead magnet (suscripción + envío de recurso)
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
		logger.LogFunction("error", constants.ServerMessages.Errors["IncompletData"], err.Error())
		setResponse(http.StatusBadRequest, false, constants.FrontendMessages.Errors["IncompletData"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Validate email format
	if request.Email == "" || !services.IsValidEmailFormat(request.Email) {
		logger.LogFunction("error", constants.ServerMessages.Errors["InvalidEmail"], request.Email)
		setResponse(http.StatusBadRequest, false, constants.FrontendMessages.Errors["InvalidEmail"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// Tags proccesing
	var tags []string
	if len(request.Tags) > 0 {
		tags = request.Tags
	}

	// Add resource tag
	resourceTag := "resource-" + request.ResourceID
	tags = append(tags, resourceTag)

	// Process the new subscription
	logger.LogFunction("info", constants.ServerMessages.Info["RequestProcessing"], request)
	result, err := services.ProcessSubscription(request.Email, string(models.SubscriptionSourceLeadMagnet), tags)
	if err != nil {
		setResponse(http.StatusInternalServerError, false, constants.FrontendMessages.Errors["ServerError"])
		c.String(response.HttpCode, response.Message)
		return
	}

	if result.AlreadySubscribed {
		logger.LogFunction("info", constants.ServerMessages.Info["NewSubscriber"], request)
		err := services.ScheduleResourceEmail(services.ResourceEmailScheduleOptions{
			Email:        request.Email,
			ResourceID:   request.ResourceID,
			FileID:       request.FileID,
			DelayMinutes: 1,
		})
		if err != nil {
			logger.LogFunction("error", constants.ServerMessages.Errors["ServerError"], err.Error())
			setResponse(http.StatusInternalServerError, false, constants.FrontendMessages.Errors["ServerError"])
			c.String(response.HttpCode, response.Message)
			return
		}
		logger.LogFunction("info", constants.ServerMessages.Info["EmailSent"], request)
	}

	logger.LogFunction("info", constants.ServerMessages.Info["SubscriptionNew"], request)

	setResponse(http.StatusCreated, true, constants.FrontendMessages.Success["ResourceSent"])
	c.Header("HX-Redirect", constants.URLs.SuccessPages.Resource)
	c.String(response.HttpCode, response.Message)
}
