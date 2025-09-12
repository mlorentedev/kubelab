package models

// ResourceRequest represents a resource request
type ResourceRequest struct {
	Email      string   `json:"email"`
	ResourceID string   `json:"resource_id"`
	FileID     string   `json:"file_id"`
	Tags       []string `json:"tags"`
	UtmSource  string   `json:"utm_source"`
}

// ResourceResult represents the result of a resource operation
type ResourceResult struct {
	HttpCode int    `json:"httpCode"`
	Success  bool   `json:"success"`
	Message  string `json:"message"`
}

type ResourceEmailScheduleOptions struct {
	Email        string
	ResourceID   string
	FileID       string
	DelayMinutes int
}

// ResourceEmailOptions represents options for sending email with resource
type ResourceEmailOptions struct {
	Email         string `json:"email"`
	ResourceID    string `json:"resourceId"`
	ResourceTitle string `json:"resourceTitle"`
	ResourceLink  string `json:"resourceLink"`
}
