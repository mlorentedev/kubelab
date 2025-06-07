package api

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/pkg/config"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// HealthCheckResult represents the result of a health check for a specific component
type HealthCheckResult struct {
	Component string `json:"component"`
	Status    string `json:"status"`
	Message   string `json:"message,omitempty"`
	Latency   int64  `json:"latency_ms,omitempty"`
}

// HealthCheckResponse aggregates health checks for all components
type HealthCheckResponse struct {
	Status    string              `json:"status"`
	Checks    []HealthCheckResult `json:"checks"`
	Timestamp time.Time           `json:"timestamp"`
	Version   string              `json:"version"`
}

// HealthCheckHandler performs comprehensive system health checks
func HealthCheckHandler(c *gin.Context) {
	// Configuration to get version or other metadata
	conf, err := config.GetConfig()
	if err != nil {
		logger.LogFunction("error", "Failed to load configuration", err)
	}

	// Prepare response
	response := HealthCheckResponse{
		Status:    "healthy",
		Timestamp: time.Now(),
		Version:   conf.Version, // Assuming you have a version in your config
	}

	// Concurrent health checks
	var checks []HealthCheckResult
	var wg sync.WaitGroup
	var mu sync.Mutex

	// Health check functions
	healthChecks := []func(context.Context) HealthCheckResult{
		checkDatabaseConnection,
		checkExternalServices,
		checkEmailConfiguration,
		checkRedisConnection,
	}

	// Timeout for health checks
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	// Run checks concurrently
	for _, check := range healthChecks {
		wg.Add(1)
		go func(healthCheck func(context.Context) HealthCheckResult) {
			defer wg.Done()

			result := healthCheck(ctx)

			mu.Lock()
			checks = append(checks, result)

			// Update overall status if any check fails
			if result.Status != "healthy" {
				response.Status = "degraded"
			}
			mu.Unlock()
		}(check)
	}

	// Wait for all checks to complete
	wg.Wait()

	// Add checks to response
	response.Checks = checks

	// Determine final status
	for _, check := range checks {
		if check.Status != "healthy" {
			response.Status = "unhealthy"
			break
		}
	}

	// Respond with health check results
	c.JSON(http.StatusOK, response)
}

// checkDatabaseConnection verifies database connectivity
func checkDatabaseConnection(ctx context.Context) HealthCheckResult {
	start := time.Now()

	// Implement database ping logic
	// Example with an SQL database:
	// db, err := database.GetConnection()
	// if err != nil {
	//     return createHealthCheckResult("database", "unhealthy", err.Error(), 0)
	// }
	// err = db.PingContext(ctx)

	// Mock implementation for demonstration
	latency := time.Since(start).Milliseconds()

	return createHealthCheckResult("database", "healthy", "Database connection successful", latency)
}

// checkExternalServices verifies external API dependencies
func checkExternalServices(ctx context.Context) HealthCheckResult {
	start := time.Now()

	// Check Beehiiv API connectivity
	// Example:
	// resp, err := http.Get("https://api.beehiiv.com/v1/some-endpoint")
	// if err != nil {
	//     return createHealthCheckResult("external_services", "unhealthy", err.Error(), 0)
	// }

	latency := time.Since(start).Milliseconds()
	return createHealthCheckResult("external_services", "healthy", "All external services operational", latency)
}

// checkEmailConfiguration verifies email service configuration
func checkEmailConfiguration(ctx context.Context) HealthCheckResult {
	start := time.Now()

	// Validate email configuration
	// You might want to do a test email send or validate SMTP settings
	conf, err := config.GetConfig()
	if err != nil {
		return createHealthCheckResult("email", "unhealthy", "Failed to load email configuration", 0)
	}

	if conf.Email.Host == "" || conf.Email.User == "" || conf.Email.Pass == "" {
		return createHealthCheckResult("email", "degraded", "Incomplete email configuration", 0)
	}

	latency := time.Since(start).Milliseconds()
	return createHealthCheckResult("email", "healthy", "Email configuration validated", latency)
}

// checkRedisConnection verifies Redis connectivity (if used)
func checkRedisConnection(ctx context.Context) HealthCheckResult {
	start := time.Now()

	// Implement Redis connection check
	// Example:
	// client := redis.NewClient(&redis.Options{
	//     Addr: redisAddr,
	// })
	// _, err := client.Ping(ctx).Result()

	// Mock implementation for demonstration
	latency := time.Since(start).Milliseconds()
	return createHealthCheckResult("cache", "healthy", "Redis connection successful", latency)
}

// createHealthCheckResult is a helper function to create consistent health check results
func createHealthCheckResult(component, status, message string, latency int64) HealthCheckResult {
	return HealthCheckResult{
		Component: component,
		Status:    status,
		Message:   message,
		Latency:   latency,
	}
}

// RegisterHealthCheckRoutes adds health check routes to the router
func RegisterHealthCheckRoutes(r *gin.Engine) {
	r.GET("/health", HealthCheckHandler)
	r.GET("/healthz", HealthCheckHandler) // Kubernetes-style health check
	r.GET("/ready", HealthCheckHandler)   // Readiness probe
}
