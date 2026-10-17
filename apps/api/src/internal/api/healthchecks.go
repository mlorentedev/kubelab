package api

import (
	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/health"
)

// RegisterHealthCheckRoutes adds the liveness and readiness routes to the router.
func RegisterHealthCheckRoutes(r *gin.Engine) {
	health.New().Register(r)
}
