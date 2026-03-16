package logger

import (
	"os"
	"runtime"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// NewLogger initializes and configures the logger
func NewLogger() *zerolog.Logger {
	// Configure output
	output := zerolog.ConsoleWriter{
		Out:        os.Stdout,
		TimeFormat: time.RFC3339,
		NoColor:    false,
	}

	// Configure logger
	logger := zerolog.New(output).
		With().
		Timestamp().
		Logger()

	// Log level based on environment
	level := zerolog.InfoLevel
	if os.Getenv("ENV") == "development" {
		level = zerolog.DebugLevel
	}
	logger = logger.Level(level)

	// Replace global logger
	log.Logger = logger

	return &logger
}

// LogFunction logs a message with information from the calling function
func LogFunction(level string, message string, data interface{}) {
	// Get information from the calling function
	pc, _, _, ok := runtime.Caller(1)
	funcName := "unknown"
	if ok {
		funcName = runtime.FuncForPC(pc).Name()
	}

	// Create log event
	event := log.With().Str("function", funcName).Interface("data", data).Logger()

	// Log with the appropriate level
	switch level {
	case "debug":
		event.Debug().Msg(message)
	case "info":
		event.Info().Msg(message)
	case "warn":
		event.Warn().Msg(message)
	case "error":
		event.Error().Msg(message)
	default:
		event.Info().Msg(message)
	}
}
