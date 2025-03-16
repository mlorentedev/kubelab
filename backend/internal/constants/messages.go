package constants

// URLs y endpoints
var URLs = struct {
	SuccessPages struct {
		Subscription string
		Resource     string
		Unsubscribe  string
		Booking      string
	}
	ErrorPages struct {
		NotFound string
	}
}{
	SuccessPages: struct {
		Subscription string
		Resource     string
		Unsubscribe  string
		Booking      string
	}{
		Subscription: "/success/subscribe",
		Resource:     "/success/resource",
		Unsubscribe:  "/success/unsubscribe",
		Booking:      "/success/booking",
	},
	ErrorPages: struct {
		NotFound string
	}{
		NotFound: "/errors/404",
	},
}

// Mensajes de respuesta para el frontend (en español)
var FrontendMessages = struct {
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
}

// Mensajes de log internos (en inglés)
var ServerMessages = struct {
	Errors map[string]string
	Info   map[string]string
	Warn   map[string]string
}{
	Errors: map[string]string{
		"InvalidEmail":       "Invalid email format",
		"IncompleteData":     "Incomplete data for operation",
		"ServerError":        "Internal server error",
		"EmailNotSubscribed": "Email not subscribed",
		"EmailConfigError":   "Email configuration error",
		"ApiError":           "API error",
		"SubscriptionError":  "Subscription error",
	},
	Info: map[string]string{
		"SubscriberExists":   "Subscriber already exists",
		"SubscriberNotFound": "Subscriber not found",
		"NewSubscriber":      "New subscriber created",
		"TagAdded":           "Tag added to subscriber",
		"UserUnsubscribed":   "User unsubscribed successfully",
		"EmailSent":          "Email sent successfully",
		"RequestProcessing":  "Processing request",
	},
	Warn: map[string]string{
		"EmptyTag":           "Empty tag not added",
		"EmailDeliveryIssue": "Email delivery issue",
	},
}
