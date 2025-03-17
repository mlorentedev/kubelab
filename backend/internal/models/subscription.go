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

// SubscriptionRequest representa una solicitud de suscripción
type SubscriptionRequest struct {
	Email     string   `json:"email" binding:"required,email"`
	Tags      []string `json:"tags"`
	UtmSource string   `json:"utm_source"`
}

// SubscriptionResult representa el resultado de una operación de suscripción
type SubscriptionResult struct {
	HttpCode          int    `json:"httpCode"`
	Success           bool   `json:"success"`
	Message           string `json:"message"`
	SubscriberID      string `json:"subscriberId,omitempty"`
	AlreadySubscribed bool   `json:"alreadySubscribed,omitempty"`
}

// UnsubscriptionRequest representa una solicitud de cancelación de suscripción
type UnsubscriptionRequest struct {
	Email string `json:"email" binding:"required"`
}

// UnsubscriptionResult representa el resultado de una operación de cancelación de suscripción
type UnsubscriptionResult struct {
	HttpCode int    `json:"httpCode"`
	Success  bool   `json:"success"`
	Message  string `json:"message"`
}
