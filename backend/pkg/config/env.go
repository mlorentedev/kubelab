package config

import (
	"errors"
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
	"github.com/rs/zerolog/log"
)

// Config contiene todas las variables de entorno
type Config struct {
	Env     string
	Version string
	Site    struct {
		Title  string
		Author string
		Domain string
		Mail   string
		URL    string
	}
	Beehiiv struct {
		APIKey string
		PubID  string
	}
	Email struct {
		Host   string
		Port   string
		Secure bool
		User   string
		Pass   string
	}
	GitHub struct {
		APIKey string
	}
	DockerHub struct {
		Username string
		Token    string
	}
	Frontend struct {
		Host string
		Port string
	}
}

var config *Config

// GetConfig devuelve la configuración global y un error si falla
func GetConfig() (*Config, error) {

	// Return cached config if it exists
	if config != nil {
		return config, nil
	}

	possiblePaths := []string{
		".env",
		"../.env",
		"../../.env",
		"/../../.env",
		"/app/.env",
	}

	envLoaded := false
	for _, path := range possiblePaths {
		if err := godotenv.Load(path); err == nil {
			log.Info().Str("path", path).Msg("Successfully loaded .env file")
			envLoaded = true
			break
		}
	}

	if !envLoaded {
		log.Warn().Msg("Could not load .env file from any location")
	}

	cfg := &Config{}

	// Cargar variables de entorno
	cfg.Env = os.Getenv("ENV")
	cfg.Version = os.Getenv("VERSION")
	cfg.Site.Title = os.Getenv("SITE_TITLE")
	cfg.Site.Author = os.Getenv("SITE_AUTHOR")
	cfg.Site.Domain = os.Getenv("SITE_DOMAIN")
	cfg.Site.Mail = os.Getenv("SITE_MAIL")
	cfg.Site.URL = os.Getenv("SITE_URL")
	cfg.Beehiiv.APIKey = os.Getenv("BEEHIIV_API_KEY")
	cfg.Beehiiv.PubID = os.Getenv("BEEHIIV_PUB_ID")
	cfg.Email.Host = os.Getenv("EMAIL_HOST")
	cfg.Email.Port = os.Getenv("EMAIL_PORT")
	cfg.Email.User = os.Getenv("EMAIL_USER")
	cfg.Email.Pass = os.Getenv("EMAIL_PASS")
	cfg.GitHub.APIKey = os.Getenv("GITHUB_API_KEY")
	cfg.DockerHub.Username = os.Getenv("DOCKERHUB_USERNAME")
	cfg.DockerHub.Token = os.Getenv("DOCKERHUB_TOKEN")
	cfg.Frontend.Host = os.Getenv("FRONTEND_HOST")
	cfg.Frontend.Port = os.Getenv("FRONTEND_PORT")
	cfg.Email.Secure = true

	// Validar configuración
	if !validateConfig(cfg) {
		return nil, errors.New("invalid environment configuration")
	}

	return cfg, nil
}

// validateConfig verifies that the configuration is valid
func validateConfig(cfg *Config) bool {
	// Validate required environment field
	if cfg.Env == "" {
		cfg.Env = "development" // Default to development if not specified
		log.Info().Msg("No environment specified, defaulting to development")
	} else if cfg.Env != "development" && cfg.Env != "staging" && cfg.Env != "production" {
		log.Error().Str("env", cfg.Env).Msg("Invalid environment value, must be development, staging, or production")
		return false
	}

	// Check if we're in production mode
	isProduction := cfg.Env == "production"

	// Validate site information
	if cfg.Site.Title == "" {
		if isProduction {
			log.Error().Msg("Site title is required in production")
			return false
		}
		log.Warn().Msg("Site title is missing")
	}

	if cfg.Site.Domain == "" {
		if isProduction {
			log.Error().Msg("Site domain is required in production")
			return false
		}
		log.Warn().Msg("Site domain is missing")
		cfg.Site.Domain = "localhost" // Default for development
	}

	// Validate email format for site mail
	if cfg.Site.Mail != "" {
		if !strings.Contains(cfg.Site.Mail, "@") || !strings.Contains(cfg.Site.Mail, ".") {
			log.Error().Str("email", cfg.Site.Mail).Msg("Invalid email format")
			return false
		}
	} else if isProduction {
		log.Error().Msg("Site email is required in production")
		return false
	}

	// Validate or construct site URL
	if cfg.Site.URL == "" {
		// Construct URL from domain if not provided
		if isProduction {
			cfg.Site.URL = "https://" + cfg.Site.Domain
		} else {
			cfg.Site.URL = "http://" + cfg.Site.Domain
			if cfg.Frontend.Port != "" {
				cfg.Site.URL += ":" + cfg.Frontend.Port
			}
		}
		log.Info().Str("url", cfg.Site.URL).Msg("Constructed site URL")
	} else {
		// Basic URL validation
		if !strings.HasPrefix(cfg.Site.URL, "http://") && !strings.HasPrefix(cfg.Site.URL, "https://") {
			log.Error().Str("url", cfg.Site.URL).Msg("Site URL must start with http:// or https://")
			return false
		}
	}

	// Validate ports
	if !validatePort(cfg.Email.Port) {
		log.Error().Str("port", cfg.Email.Port).Msg("Invalid email port")
		return false
	}

	if !validatePort(cfg.Frontend.Port) {
		log.Error().Str("port", cfg.Frontend.Port).Msg("Invalid frontend port")
		return false
	}

	// In production, validate email configuration
	if isProduction {
		if cfg.Email.Host == "" || cfg.Email.Port == "" || cfg.Email.User == "" || cfg.Email.Pass == "" {
			log.Error().Msg("Complete email configuration is required in production")
			return false
		}
	} else if hasPartialEmailConfig(cfg) {
		log.Warn().Msg("Incomplete email configuration")
	}

	// In production, validate Beehiiv configuration
	if isProduction {
		if cfg.Beehiiv.APIKey == "" || cfg.Beehiiv.PubID == "" {
			log.Error().Msg("Complete Beehiiv configuration is required in production")
			return false
		}
	} else if hasPartialBeehiivConfig(cfg) {
		log.Warn().Msg("Incomplete Beehiiv configuration")
	}

	// Validate GitHub API Key format if provided
	if cfg.GitHub.APIKey != "" && len(cfg.GitHub.APIKey) < 20 {
		log.Warn().Msg("GitHub API key seems too short")
	}

	// Validate DockerHub credentials if provided
	if hasPartialDockerHubConfig(cfg) {
		log.Warn().Msg("Incomplete DockerHub credentials")
	}

	return true
}

// validatePort checks if a port string is a valid port number
func validatePort(port string) bool {
	if port == "" {
		return true // Empty port is considered valid (will use default)
	}

	portNum, err := strconv.Atoi(port)
	return err == nil && portNum > 0 && portNum <= 65535
}

// hasPartialEmailConfig checks if email configuration is partially provided
func hasPartialEmailConfig(cfg *Config) bool {
	hasAny := cfg.Email.Host != "" || cfg.Email.Port != "" || cfg.Email.User != "" || cfg.Email.Pass != ""
	hasAll := cfg.Email.Host != "" && cfg.Email.Port != "" && cfg.Email.User != "" && cfg.Email.Pass != ""
	return hasAny && !hasAll
}

// hasPartialBeehiivConfig checks if Beehiiv configuration is partially provided
func hasPartialBeehiivConfig(cfg *Config) bool {
	hasAny := cfg.Beehiiv.APIKey != "" || cfg.Beehiiv.PubID != ""
	hasAll := cfg.Beehiiv.APIKey != "" && cfg.Beehiiv.PubID != ""
	return hasAny && !hasAll
}

// hasPartialDockerHubConfig checks if DockerHub configuration is partially provided
func hasPartialDockerHubConfig(cfg *Config) bool {
	hasAny := cfg.DockerHub.Username != "" || cfg.DockerHub.Token != ""
	hasAll := cfg.DockerHub.Username != "" && cfg.DockerHub.Token != ""
	return hasAny && !hasAll
}
