package models

// ResourceRequest representa una solicitud de recurso
type ResourceRequest struct {
	Email      string   `form:"email"`
	ResourceID string   `form:"resource_id"`
	FileID     string   `form:"file_id"`
	Tags       []string `form:"tags"`
	UtmSource  string   `form:"utm_source"`
}

// ResourceResult representa el resultado de una operación de recurso
type ResourceResult struct {
	HttpCode int    `json:"httpCode"`
	Success  bool   `json:"success"`
	Message  string `json:"message"`
}

// ResourceEmailOptions representa opciones para envío de email con recurso
type ResourceEmailOptions struct {
	Email         string `json:"email"`
	ResourceID    string `json:"resourceId"`
	ResourceTitle string `json:"resourceTitle"`
	ResourceLink  string `json:"resourceLink"`
}
