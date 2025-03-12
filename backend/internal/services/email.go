package services

import (
	"fmt"
	"net/smtp"
	"time"

	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// Estructura para opciones de programación de emails
type ResourceEmailScheduleOptions struct {
	Email        string
	ResourceID   string
	FileID       string
	DelayMinutes int
}

// SendResourceEmail envía un email con un recurso
func SendResourceEmail(options models.ResourceEmailOptions) (bool, error) {
	if !ValidateEmailConfiguration() {
		return false, fmt.Errorf("email configuration is invalid")
	}

	if options.Email == "" || options.ResourceLink == "" {
		logger.LogFunction("error", "Incomplete data for email sending", options)
		return false, fmt.Errorf("incomplete data for email sending")
	}

	// Generar HTML para el cuerpo del email
	htmlBody := generateResourceEmailHTML(options)

	// Configurar cabeceras del email
	headers := make(map[string]string)
	headers["From"] = fmt.Sprintf("\"%s\" <%s>", conf.Site.Author, conf.Email.User)
	headers["To"] = options.Email
	headers["Subject"] = fmt.Sprintf("Aquí tienes: %s", options.ResourceTitle)
	headers["MIME-Version"] = "1.0"
	headers["Content-Type"] = "text/html; charset=UTF-8"
	headers["Precedence"] = "bulk"
	headers["X-Auto-Response-Suppress"] = "All"
	headers["List-Unsubscribe"] = fmt.Sprintf("<%s/unsubscribe>", conf.Site.URL)
	headers["X-Site-Origin"] = conf.Site.Title

	// Construir mensaje completo
	message := ""
	for k, v := range headers {
		message += fmt.Sprintf("%s: %s\r\n", k, v)
	}
	message += "\r\n" + htmlBody

	// Enviar email
	auth := smtp.PlainAuth("", conf.Email.User, conf.Email.Pass, conf.Email.Host)
	err := smtp.SendMail(
		fmt.Sprintf("%s:%s", conf.Email.Host, conf.Email.Port),
		auth,
		conf.Email.User,
		[]string{options.Email},
		[]byte(message),
	)

	if err != nil {
		handleEmailError(err)
		return false, err
	}

	logger.LogFunction("info", "Email sent successfully", map[string]string{
		"email":      options.Email,
		"resourceId": options.ResourceID,
	})

	return true, nil
}

// ScheduleResourceEmail programa el envío de un email con recurso (con delay)
func ScheduleResourceEmail(options ResourceEmailScheduleOptions) error {
	if options.DelayMinutes <= 0 {
		options.DelayMinutes = 1
	}

	// Utilizar goroutine para simular delay
	go func() {
		time.Sleep(time.Duration(options.DelayMinutes) * time.Minute)

		emailSent, err := SendResourceEmail(models.ResourceEmailOptions{
			Email:         options.Email,
			ResourceID:    options.ResourceID,
			ResourceTitle: GenerateResourceTitle(options.ResourceID, ""),
			ResourceLink:  GenerateResourceURL(options.FileID),
		})

		if err != nil || !emailSent {
			logger.LogFunction("warn", "Email delivery issue", map[string]string{
				"email":      options.Email,
				"resourceId": options.ResourceID,
				"fileId":     options.FileID,
			})
		} else {
			logger.LogFunction("info", "Delayed email sent successfully", map[string]string{
				"email":      options.Email,
				"resourceId": options.ResourceID,
			})
		}
	}()

	return nil
}

// ValidateEmailConfiguration valida que exista la configuración de email
func ValidateEmailConfiguration() bool {
	if conf.Email.Host == "" || conf.Email.Port == "" || conf.Email.User == "" || conf.Email.Pass == "" {
		logger.LogFunction("error", "Missing email configuration", nil)
		return false
	}
	return true
}

// generateResourceEmailHTML genera el HTML para el email de recurso
func generateResourceEmailHTML(options models.ResourceEmailOptions) string {
	year := time.Now().Year()

	return fmt.Sprintf(`
<div>
  <p>Hola,</p>
  <p>Aquí tienes tu %s.</p>
  <p><a href="%s">Ver</a></p>
  <p>Si el enlace no funciona, copia esta URL: %s</p>
  <p>---</p>
  <p>© %d %s | <a href="%s">%s</a></p>
</div>
`, options.ResourceTitle, options.ResourceLink, options.ResourceLink, year, conf.Site.Title, conf.Site.URL, conf.Site.URL)
}

// handleEmailError maneja errores de envío de email
func handleEmailError(err error) {
	logger.LogFunction("error", "Error sending email", err.Error())
}
