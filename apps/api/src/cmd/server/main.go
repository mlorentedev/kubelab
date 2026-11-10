package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/api"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
	"github.com/mlorentedev/kubelab/apps/api/pkg/logger"
)

func main() {
	logger := logger.NewLogger()

	conf, err := config.GetConfig()
	if err != nil {
		logger.Fatal().Err(err).Msg("Error loading configuration")
	}

	gin.SetMode(gin.ReleaseMode)

	r := gin.New()

	r.Use(gin.Logger())

	r.Use(gin.Recovery())

	r.Use(api.CorsMiddleware())

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	forgeView := api.NewForgeView(ctx, conf)

	api.SetupRoutes(r, forgeView)

	api.StartForgeReconcile(ctx, conf, forgeView)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	logger.Info().Msgf("Server starting on port %s", port)
	r.Run(":" + port)
}
