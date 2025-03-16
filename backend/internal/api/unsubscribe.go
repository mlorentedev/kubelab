package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/constants"
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

	// Check if the email is already subscribed
	existingSubscriber, err := services.CheckSubscriber(request.Email)
	if err != nil {
		logger.LogFunction("error", constants.ServerMessages.Errors["ServerError"], err.Error())
		setResponse(http.StatusInternalServerError, false, constants.FrontendMessages.Errors["ServerError"])
		c.String(response.HttpCode, response.Message)
		return
	}

	// If the email is already subscribed, proceed to unsubscribe
	// If the email is not subscribed, return a conflict response
	if existingSubscriber.Success && existingSubscriber.Subscriber != nil {
		_, err = services.UnsubscribeUser(request.Email)
		if err != nil {
			logger.LogFunction("error", constants.ServerMessages.Errors["ServerError"], err.Error())
			setResponse(http.StatusInternalServerError, false, constants.FrontendMessages.Errors["ServerError"])
			c.String(response.HttpCode, response.Message)
			return
		} else {
			logger.LogFunction("info", constants.ServerMessages.Info["Unsubscribed"], request.Email)
			setResponse(http.StatusOK, true, constants.FrontendMessages.Success["Unsubscription"])
			c.Header("HX-Redirect", constants.URLs.SuccessPages.Unsubscribe)
			c.String(response.HttpCode, response.Message)
		}
	} else if !existingSubscriber.Success {
		logger.LogFunction("info", constants.ServerMessages.Info["NotSubscribed"], request.Email)
		setResponse(http.StatusConflict, false, constants.FrontendMessages.Errors["EmailNotSubscribed"])
		c.String(response.HttpCode, response.Message)
		return
	}

}
