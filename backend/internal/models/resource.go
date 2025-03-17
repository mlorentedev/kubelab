package models

// ResourceRequest representa una solicitud de recurso
type ResourceRequest struct {
	Email      string   `json:"email"`
	ResourceID string   `json:"resource_id"`
	FileID     string   `json:"file_id"`
	Tags       []string `json:"tags"`
	UtmSource  string   `json:"utm_source"`
}

// ResourceResult representa el resultado de una operación de recurso
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

// ResourceEmailOptions representa opciones para envío de email con recurso
type ResourceEmailOptions struct {
	Email         string `json:"email"`
	ResourceID    string `json:"resourceId"`
	ResourceTitle string `json:"resourceTitle"`
	ResourceLink  string `json:"resourceLink"`
}
