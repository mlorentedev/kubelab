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

// IsValidEmailFormat determines if an email has valid format
func IsValidEmailFormat(email string) bool {
	re := regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`)
	return re.MatchString(email)
}

// GetTagsForNewSubscriber determines which tags to apply to a new subscriber
func GetTagsForNewSubscriber(customTags []string) []string {
	result := append([]string{"new"}, customTags...)
	return result
}

// GenerateResourceTitle generates the title for a resource based on its ID
func GenerateResourceTitle(resourceID string, customTitle string) string {
	if customTitle != "" {
		return customTitle
	}
	return resourceID
}

// GenerateResourceURL generates the URL of a resource based on its fileId
func GenerateResourceURL(fileID string) string {
	return fmt.Sprintf("https://drive.google.com/file/d/%s/view?usp=drive_link", fileID)
}

// GetEmailDelay calculates a delay for email sending (in milliseconds)
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
