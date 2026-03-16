package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// CorsMiddleware configura CORS para la API
func CorsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Writer.Header().Set("Access-Control-Allow-Origin", "*")

		// Allow common methods
		c.Writer.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

		// Allow all HTMX headers and other common headers
		c.Writer.Header().Set("Access-Control-Allow-Headers",
			"Content-Type, Content-Length, Accept-Encoding, X-CSRF-Token, Authorization, "+
				"HX-Request, HX-Trigger, HX-Trigger-Name, HX-Target, HX-Current-URL, HX-Boost")

		// Expose HTMX-specific response headers
		c.Writer.Header().Set("Access-Control-Expose-Headers",
			"HX-Redirect, HX-Trigger, HX-Refresh, HX-Location")

		// Allow credentials
		c.Writer.Header().Set("Access-Control-Allow-Credentials", "true")

		// Handle preflight OPTIONS requests
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(http.StatusNoContent) // No content needed for OPTIONS
			return
		}

	}
}
