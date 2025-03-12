package services

import (
	"fmt"
	"regexp"
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
	return fmt.Sprintf("Recurso %s", resourceID)
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
