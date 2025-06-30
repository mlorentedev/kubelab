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

	// Cargar variables de entorno
	_, err := config.GetConfig()
	if err != nil {
		logger.Fatal().Err(err).Msg("Error loading configuration")
	}

	gin.SetMode(gin.ReleaseMode)

	// Configurar router sin Logger y Recovery por defecto
	r := gin.New()

	// Usar middlewares personalizados (Logger, Recovery)
	r.Use(gin.Logger())
	r.Use(gin.Recovery())

	// Configurar CORS
	r.Use(api.CorsMiddleware())

	api.SetupRoutes(r)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	logger.Info().Msgf("Server starting on port %s", port)
	r.Run(":" + port)
}
