package main

import (
	"log"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"github.com/mlorentedev/mlorente-backend/internal/api"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

func main() {
	// Cargar variables de entorno
	if err := godotenv.Load(); err != nil {
		log.Println("No .env file found")
	}

	// Configurar logger
	logger := logger.NewLogger()

	// Configurar router
	r := gin.Default()

	// Configurar CORS
	r.Use(api.CorsMiddleware())

	// Configurar rutas
	api.SetupRoutes(r)

	// Iniciar servidor
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	logger.Info().Msgf("Server starting on port %s", port)
	r.Run(":" + port)
}
