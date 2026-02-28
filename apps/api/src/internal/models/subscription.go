package models

// SubscriptionSource defines subscription sources
type SubscriptionSource string

const (
	SubscriptionSourceLandingPage SubscriptionSource = "landing_page"
	SubscriptionSourceLeadMagnet  SubscriptionSource = "lead_magnet"
	SubscriptionSourceNewsletter  SubscriptionSource = "newsletter"
)

// SubscriptionTag defines subscription tags
type SubscriptionTag string

const (
	SubscriptionTagNewSubscriber      SubscriptionTag = "new"
	SubscriptionTagExistingSubscriber SubscriptionTag = "existing"
)

// Subscriber represents a subscriber
type Subscriber struct {
	ID    string   `json:"id"`
	Email string   `json:"email"`
	Tags  []string `json:"tags"`
}

// SubscriptionRequest represents a subscription request
type SubscriptionRequest struct {
	Email     string   `json:"email" binding:"required,email"`
	Tags      []string `json:"tags"`
	UtmSource string   `json:"utm_source"`
}

// SubscriptionResult represents the result of a subscription operation
type SubscriptionResult struct {
	HttpCode          int    `json:"httpCode"`
	Success           bool   `json:"success"`
	Message           string `json:"message"`
	SubscriberID      string `json:"subscriberId,omitempty"`
	AlreadySubscribed bool   `json:"alreadySubscribed,omitempty"`
}

// UnsubscriptionRequest represents an unsubscription request
type UnsubscriptionRequest struct {
	Email string `json:"email" binding:"required"`
}

// UnsubscriptionResult represents the result of an unsubscription operation
type UnsubscriptionResult struct {
	HttpCode int    `json:"httpCode"`
	Success  bool   `json:"success"`
	Message  string `json:"message"`
}
