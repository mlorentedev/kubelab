package constants

// All messages consolidated in a single structure
var Messages = struct {
	// Frontend messages (displayed to users - in Spanish)
	Frontend struct {
		Errors  map[string]string
		Success map[string]string
	}
	// Backend messages (for logging - in English)
	Backend struct {
		Error map[string]string
		Info  map[string]string
		Warn  map[string]string
	}
	// Service-specific messages (for direct reference - in Spanish and English)
	Service struct {
		Subscription map[string]string
		Email        map[string]string
		Resource     map[string]string
	}
}{
	Frontend: struct {
		Errors  map[string]string
		Success map[string]string
	}{
		Errors: map[string]string{
			"InvalidEmail":        "Correo electrónico inválido",
			"IncompleteData":      "Datos incompletos",
			"ServerError":         "Error interno del servidor",
			"EmailNotSubscribed":  "Este email no está en la lista",
			"EmailConfigError":    "Error en la configuración de email",
			"TagsUpdateError":     "Error al actualizar los tags del suscriptor",
			"SubscriptionError":   "Ya estás suscrito",
			"UnsubscriptionError": "Error al cancelar la suscripción",
		},
		Success: map[string]string{
			"SubscriptionNew":     "Nuevo suscriptor añadido",
			"SubscriptionUpdated": "Suscriptor existente actualizado",
			"Unsubscription":      "Se ha cancelado tu suscripción correctamente",
			"ResourceSent":        "Recurso enviado correctamente",
			"EmailSent":           "Email enviado correctamente",
		},
	},
	Backend: struct {
		Error map[string]string
		Info  map[string]string
		Warn  map[string]string
	}{
		Error: map[string]string{
			// General errors
			"InvalidEmail":   "Invalid email format",
			"IncompleteData": "Incomplete data for operation",
			"ServerError":    "Internal server error",

			// API and request errors
			"ApiError":              "API error",
			"RequestCreationError":  "Error creating HTTP request",
			"RequestExecutionError": "Error executing HTTP request",
			"ResponseReadError":     "Error reading response body",
			"MarshalError":          "Error marshaling data",
			"UnmarshalError":        "Error unmarshaling response data",

			// Subscription errors
			"SubscriptionError":     "Subscription error",
			"CheckSubscriberError":  "Error checking subscriber status",
			"CreateSubscriberError": "Error creating new subscriber",
			"AddTagError":           "Error adding tag to subscriber",
			"UnsubscribeError":      "Error unsubscribing user",
			"EmailNotSubscribed":    "Email not subscribed",
			"TagsUpdateError":       "Error updating subscriber tags",

			// Email errors
			"EmailConfigError":   "Email configuration error",
			"EmailConfigMissing": "Missing email configuration",
			"SendEmailError":     "Error sending email",
		},
		Info: map[string]string{
			// General info
			"RequestProcessing": "Processing request",

			// Subscription info
			"SubscriberExists":       "Subscriber already exists",
			"SubscriberNotFound":     "Subscriber not found",
			"NewSubscriber":          "New subscriber created",
			"TagAdded":               "Tag added to subscriber",
			"UserUnsubscribed":       "User unsubscribed successfully",
			"SubscriptionProcessing": "Processing subscription request",

			// Email info
			"EmailSent":             "Email sent successfully",
			"DelayedEmailScheduled": "Delayed email has been scheduled",
			"DelayedEmailSent":      "Delayed email sent successfully",
			"ResourceSent":          "Resource sent successfully",
		},
		Warn: map[string]string{
			"EmptyTag":             "Empty tag not added",
			"EmailDeliveryIssue":   "Email delivery issue",
			"MinimumDelayEnforced": "Minimum delay enforced for email delivery",
		},
	},
	Service: struct {
		Subscription map[string]string
		Email        map[string]string
		Resource     map[string]string
	}{
		Subscription: map[string]string{
			// Spanish messages for frontend responses
			"Updated":     "Suscriptor existente actualizado.",
			"New":         "Nuevo suscriptor añadido.",
			"Error":       "No se pudo completar la suscripción.",
			"TagsError":   "Error al actualizar los tags del suscriptor.",
			"ServerError": "Error interno del servidor.",

			// English messages for function returns
			"SubscriberExists": "Subscriber already exists",
			"SubscriberAdded":  "New subscriber added successfully",
			"TagsUpdated":      "Tags updated successfully",
		},
		Email: map[string]string{
			"Sent":          "Email sent successfully",
			"ScheduledSent": "Scheduled email sent successfully",
			"Failed":        "Failed to send email",
			"InvalidConfig": "Invalid email configuration",
		},
		Resource: map[string]string{
			"Sent":      "Resource sent successfully",
			"Failed":    "Failed to send resource",
			"Scheduled": "Resource delivery scheduled",
		},
	},
}
