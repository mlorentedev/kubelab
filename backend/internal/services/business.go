package services

import (
	"fmt"
	"regexp"
	"time"

	"github.com/google/uuid"

	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// IsValidEmailFormat determina si un email tiene formato válido
func IsValidEmailFormat(email string) bool {
	re := regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`)
	return re.MatchString(email)
}

// GetTagsForNewSubscriber determina qué tags aplicar a un nuevo suscriptor
func GetTagsForNewSubscriber(customTags []string) []string {
	result := append([]string{"new"}, customTags...)
	return result
}

// GenerateResourceTitle genera el título para un recurso basado en su ID
func GenerateResourceTitle(resourceID string, customTitle string) string {
	if customTitle != "" {
		return customTitle
	}
	return resourceID
}

// GenerateResourceURL genera la URL de un recurso basado en su fileId
func GenerateResourceURL(fileID string) string {
	return fmt.Sprintf("https://drive.google.com/file/d/%s/view?usp=drive_link", fileID)
}

// GetEmailDelay calcula un retraso para envío de emails (en milisegundos)
func GetEmailDelay(minutes int) int {
	if minutes <= 0 {
		minutes = 1
	}
	return minutes * 60 * 1000
}

// ValidateEmailConfiguration validates that email configuration exists
func ValidateEmailConfiguration() bool {
	if conf.Email.Host == "" || conf.Email.Port == "" || conf.Email.User == "" || conf.Email.Pass == "" {
		logger.LogFunction("error", constants.Messages.Backend.Error["EmailConfigMissing"], nil)
		return false
	}
	return true
}

func generateUniqueID() string {
	return fmt.Sprintf("%d-%s", time.Now().UnixNano(),
		uuid.New().String()[:8])
}

// generateResourceEmailHTML generates HTML for the resource email
func generateResourceEmailHTML(options models.ResourceEmailOptions) string {
	year := time.Now().Year()

	return fmt.Sprintf(`
	<html lang="es">
	<head>
		<meta charset="UTF-8">
		<meta name="viewport" content="width=device-width, initial-scale=1.0">
		<title>%s</title>
	</head>
	<body>
		<div>
		<p>Aquí lo tienes. Que te sea útil: <a href="%s">Ver</a></p>
		<br>
		<p>Si el enlace no funciona, copia esta URL: %s</p>
		<br>
		<p>Si tienes dudas, no dudes en escribirme.</p>
		<br>
		<br>
		<p>Uso es todo.</p>
		<p>Manu</p>
		<br>
		</div>
	</body>
	<footer>
		<p>© %d <a href="%s">%s</a></p>
	</footer>
	</html>
	`, options.ResourceTitle,
		options.ResourceLink,
		options.ResourceLink,
		year,
		conf.Site.URL,
		conf.Site.URL)
}
