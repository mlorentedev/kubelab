package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/internal/services"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// ResourceEmailHandler maneja las solicitudes para enviar email con recurso
func ResourceEmailHandler(c *gin.Context) {
	var request struct {
		Email         string `json:"email" binding:"required"`
		ResourceID    string `json:"resourceId" binding:"required"`
		ResourceTitle string `json:"resourceTitle"`
		ResourceLink  string `json:"resourceLink" binding:"required"`
	}

	if err := c.ShouldBindJSON(&request); err != nil {
		logger.LogFunction("error", "Error in resource email endpoint", err.Error())
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

	// Enviar email con recurso
	resourceTitle := request.ResourceTitle
	if resourceTitle == "" {
		resourceTitle = services.GenerateResourceTitle(request.ResourceID, "")
	}

	emailSent, err := services.SendResourceEmail(models.ResourceEmailOptions{
		Email:         request.Email,
		ResourceID:    request.ResourceID,
		ResourceTitle: resourceTitle,
		ResourceLink:  request.ResourceLink,
	})

	if err != nil {
		logger.LogFunction("error", "Error sending resource email", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": "Error interno del servidor.",
		})
		return
	}

	if emailSent {
		logger.LogFunction("info", "Resource email sent successfully", map[string]string{"email": request.Email, "resourceId": request.ResourceID})
		c.JSON(http.StatusOK, gin.H{
			"success": true,
			"message": "Email enviado correctamente.",
		})
	} else {
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"message": "Error interno del servidor.",
		})
	}
}
