package logger

import (
	"os"
	"runtime"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// NewLogger inicializa y configura el logger
func NewLogger() *zerolog.Logger {
	// Configurar output
	output := zerolog.ConsoleWriter{
		Out:        os.Stdout,
		TimeFormat: time.RFC3339,
		NoColor:    false,
	}

	// Configurar logger
	logger := zerolog.New(output).
		With().
		Timestamp().
		Logger()

	// Nivel de log basado en entorno
	level := zerolog.InfoLevel
	if os.Getenv("ENV") == "development" {
		level = zerolog.DebugLevel
	}
	logger = logger.Level(level)

	// Reemplazar logger global
	log.Logger = logger

	return &logger
}

// LogFunction registra un mensaje con información de la función que lo llama
func LogFunction(level string, message string, data interface{}) {
	// Obtener información de la función que llama
	pc, _, _, ok := runtime.Caller(1)
	funcName := "unknown"
	if ok {
		funcName = runtime.FuncForPC(pc).Name()
	}

	// Crear evento de log
	event := log.With().Str("function", funcName).Interface("data", data).Logger()

	// Registrar con el nivel adecuado
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
