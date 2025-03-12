package models

// SubscriptionSource define las fuentes de suscripción
type SubscriptionSource string

const (
	SubscriptionSourceLandingPage SubscriptionSource = "landing_page"
	SubscriptionSourceLeadMagnet  SubscriptionSource = "lead_magnet"
	SubscriptionSourceNewsletter  SubscriptionSource = "newsletter"
)

// SubscriptionTag define los tags de suscripción
type SubscriptionTag string

const (
	SubscriptionTagNewSubscriber      SubscriptionTag = "new"
	SubscriptionTagExistingSubscriber SubscriptionTag = "existing"
)

// Subscriber representa un suscriptor
type Subscriber struct {
	ID    string   `json:"id"`
	Email string   `json:"email"`
	Tags  []string `json:"tags"`
}

// SubscriptionResult representa el resultado de una operación de suscripción
type SubscriptionResult struct {
	Success           bool   `json:"success"`
	Message           string `json:"message"`
	SubscriberID      string `json:"subscriberId,omitempty"`
	AlreadySubscribed bool   `json:"alreadySubscribed,omitempty"`
}

// SubscriptionRequest representa una solicitud de suscripción
type SubscriptionRequest struct {
	Email     string   `json:"email" binding:"required"`
	Tags      []string `json:"tags"`
	UtmSource string   `json:"utmSource"`
}

// UnsubscriptionRequest representa una solicitud de cancelación de suscripción
type UnsubscriptionRequest struct {
	Email string `json:"email" binding:"required"`
}

// ResourceRequest representa una solicitud de recurso
type ResourceRequest struct {
	Email      string   `json:"email" binding:"required"`
	ResourceID string   `json:"resourceId" binding:"required"`
	FileID     string   `json:"fileId" binding:"required"`
	Tags       []string `json:"tags"`
	UtmSource  string   `json:"utmSource"`
}

// ResourceEmailOptions representa opciones para envío de email con recurso
type ResourceEmailOptions struct {
	Email         string `json:"email"`
	ResourceID    string `json:"resourceId"`
	ResourceTitle string `json:"resourceTitle"`
	ResourceLink  string `json:"resourceLink"`
}
