package main

import (
	"os"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/mlorente-backend/internal/api"
	"github.com/mlorentedev/mlorente-backend/pkg/config"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

func main() {
	// Configurar logger
	logger := logger.NewLogger()

	_, err := config.GetConfig()
	if err != nil {
		logger.Fatal().Err(err).Msg("Error loading configuration")
	}

	gin.SetMode(gin.ReleaseMode)

	r := gin.New()

	r.Use(gin.Logger())
	r.Use(gin.Recovery())

	r.Use(api.CorsMiddleware())

	api.SetupRoutes(r)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	logger.Info().Msgf("Server starting on port %s", port)
	r.Run(":" + port)
}
