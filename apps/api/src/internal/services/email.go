package services

import (
	"fmt"
	"net/smtp"
	"time"

	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// SendResourceEmail sends an email with a resource
func SendResourceEmail(options models.ResourceEmailOptions) (bool, error) {
	if !ValidateEmailConfiguration() {
		logger.LogFunction("error", constants.Messages.Backend.Error["EmailConfigMissing"], nil)
		return false, fmt.Errorf(constants.Messages.Service.Email["InvalidConfig"])
	}

	if options.Email == "" || options.ResourceLink == "" {
		logger.LogFunction("error", constants.Messages.Backend.Error["IncompleteData"], options)
		return false, fmt.Errorf("incomplete data for email sending")
	}

	// Generate HTML for email body
	htmlBody := generateResourceEmailHTML(options)

	// Configure email headers
	headers := make(map[string]string)
	headers["From"] = conf.Email.From
	headers["Reply-To"] = conf.Site.Mail
	headers["To"] = options.Email
	headers["Subject"] = fmt.Sprintf("Tu %s", options.ResourceTitle)
	headers["MIME-Version"] = "1.0"
	headers["Content-Type"] = "text/html; charset=UTF-8"
	headers["Precedence"] = "bulk"
	headers["X-Auto-Response-Suppress"] = "All"
	headers["X-Site-Origin"] = conf.Site.Title
	headers["Message-ID"] = fmt.Sprintf("<%s@%s>", generateUniqueID(), conf.Site.Domain)
	headers["Return-Path"] = conf.Email.User
	headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
	headers["List-Unsubscribe"] = fmt.Sprintf("<%s/unsubscribe>", conf.Site.URL)

	// Build complete message
	message := ""
	for k, v := range headers {
		message += fmt.Sprintf("%s: %s\r\n", k, v)
	}
	message += "\r\n" + htmlBody

	// Send email
	auth := smtp.PlainAuth("", conf.Email.User, conf.Email.Pass, conf.Email.Host)
	err := smtp.SendMail(
		fmt.Sprintf("%s:%s", conf.Email.Host, conf.Email.Port),
		auth,
		conf.Email.User,
		[]string{options.Email},
		[]byte(message),
	)

	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["SendEmailError"], err.Error())
		return false, err
	}

	logger.LogFunction("info", constants.Messages.Backend.Info["EmailSent"], map[string]string{
		"email":      options.Email,
		"resourceId": options.ResourceID,
	})

	return true, nil
}

// ScheduleResourceEmail schedules sending a resource email (with delay)
func ScheduleResourceEmail(options models.ResourceEmailScheduleOptions) error {
	// Enforce minimum delay
	if options.DelayMinutes <= 0 {
		options.DelayMinutes = 1
		logger.LogFunction("warn", constants.Messages.Backend.Warn["MinimumDelayEnforced"], map[string]string{
			"email":        options.Email,
			"resourceId":   options.ResourceID,
			"delayMinutes": "1",
		})
	}

	logger.LogFunction("info", constants.Messages.Backend.Info["DelayedEmailScheduled"], map[string]string{
		"email":        options.Email,
		"resourceId":   options.ResourceID,
		"delayMinutes": fmt.Sprintf("%d", options.DelayMinutes),
	})

	// Use goroutine to simulate delay
	go func() {
		time.Sleep(time.Duration(options.DelayMinutes) * time.Minute)

		emailSent, err := SendResourceEmail(models.ResourceEmailOptions{
			Email:         options.Email,
			ResourceID:    options.ResourceID,
			ResourceTitle: GenerateResourceTitle(options.ResourceID, ""),
			ResourceLink:  GenerateResourceURL(options.FileID),
		})

		if err != nil || !emailSent {
			logger.LogFunction("warn", constants.Messages.Backend.Warn["EmailDeliveryIssue"], map[string]string{
				"email":      options.Email,
				"resourceId": options.ResourceID,
				"fileId":     options.FileID,
				"error":      fmt.Sprintf("%v", err),
			})
		} else {
			logger.LogFunction("info", constants.Messages.Backend.Info["DelayedEmailSent"], map[string]string{
				"email":      options.Email,
				"resourceId": options.ResourceID,
			})
		}
	}()

	return nil
}
