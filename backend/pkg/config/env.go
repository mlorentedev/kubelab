package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
	"github.com/rs/zerolog/log"
)

// Config represents the complete application configuration
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
		From   string
		Secure bool
		User   string
		Pass   string
	}
	Frontend struct {
		Host string
		Port string
	}
}

var config *Config

// GetConfig retrieves the global configuration
func GetConfig() (*Config, error) {
	// Return cached config if it exists
	if config != nil {
		return config, nil
	}

	// Determine if running in GitHub Actions
	isGitHubActions := os.Getenv("GITHUB_ACTIONS") == "true"

	// Possible .env file paths
	possiblePaths := getPossibleEnvPaths()

	// Load .env file only for local development
	if !isGitHubActions {
		loadDotEnvFile(possiblePaths)
	}

	// Create and populate configuration
	cfg, err := populateConfig()
	if err != nil {
		return nil, err
	}

	// Cache the configuration
	config = cfg
	return config, nil
}

// getPossibleEnvPaths returns potential .env file locations
func getPossibleEnvPaths() []string {
	// Get the directory of the calling file
	_, filename, _, _ := runtime.Caller(0)
	baseDir := filepath.Dir(filename)

	return []string{
		".env",
		filepath.Join(baseDir, ".env"),
		filepath.Join(baseDir, "..", ".env"),
		filepath.Join(baseDir, "..", ".env.development"),
		"/app/.env",
	}
}

// loadDotEnvFile attempts to load .env file from possible paths
func loadDotEnvFile(paths []string) {
	for _, path := range paths {
		err := godotenv.Load(path)
		if err == nil {
			log.Info().Str("path", path).Msg("Successfully loaded .env file")
			return
		}
	}
	log.Warn().Msg("Could not load .env file from any location")
}

// populateConfig fills the configuration struct with environment variables
func populateConfig() (*Config, error) {
	cfg := &Config{}

	// Environment and Version
	cfg.Env = getEnvWithFallback("ENV", "development")
	cfg.Version = getEnvWithFallback("VERSION", "0.0.1")

	// Site Configuration
	cfg.Site.Title = getEnvWithFallback("SITE_TITLE", "mlorente.dev")
	cfg.Site.Author = getEnvWithFallback("SITE_AUTHOR", "Manuel Lorente")
	cfg.Site.Domain = getEnvWithFallback("SITE_DOMAIN", "mlorente.dev")
	cfg.Site.Mail = getEnvWithFallback("SITE_MAIL", "mlorentedev@gmail.com")
	cfg.Site.URL = constructSiteURL(cfg)

	// Beehiiv Configuration
	cfg.Beehiiv.APIKey = os.Getenv("BEEHIIV_API_KEY")
	cfg.Beehiiv.PubID = os.Getenv("BEEHIIV_PUB_ID")

	// Email Configuration
	cfg.Email.Host = getEnvWithFallback("EMAIL_HOST", "smtp.gmail.com")
	cfg.Email.Port = getEnvWithFallback("EMAIL_PORT", "587")
	cfg.Email.From = getEnvWithFallback("EMAIL_FROM", "noreply@mlorente.dev")
	cfg.Email.User = os.Getenv("EMAIL_USER")
	cfg.Email.Pass = os.Getenv("EMAIL_PASS")
	cfg.Email.Secure = getBoolEnv("EMAIL_SECURE", true)

	// Frontend Configuration
	cfg.Frontend.Host = getEnvWithFallback("FRONTEND_HOST", "localhost")
	cfg.Frontend.Port = getEnvWithFallback("FRONTEND_PORT", "3000")

	// Validate configuration
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}

	return cfg, nil
}

// constructSiteURL builds the site URL based on environment and configuration
func constructSiteURL(cfg *Config) string {
	// If URL is explicitly set, use it
	if url := os.Getenv("SITE_URL"); url != "" {
		return url
	}

	// Construct URL based on environment
	if cfg.Env == "production" {
		return fmt.Sprintf("https://%s", cfg.Site.Domain)
	}

	// Development URL
	port := cfg.Frontend.Port
	if port == "" {
		port = "3000"
	}
	return fmt.Sprintf("http://%s:%s", cfg.Site.Domain, port)
}

// getEnvWithFallback retrieves an environment variable with a default value
func getEnvWithFallback(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

// getBoolEnv parses a boolean environment variable
func getBoolEnv(key string, defaultValue bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}
	boolValue, err := strconv.ParseBool(value)
	if err != nil {
		log.Warn().Str("key", key).Msg("Invalid boolean value, using default")
		return defaultValue
	}
	return boolValue
}

// validateConfig checks the configuration for completeness and correctness
func validateConfig(cfg *Config) error {
	// Validate environment
	if cfg.Env != "development" && cfg.Env != "staging" && cfg.Env != "production" {
		return fmt.Errorf("invalid environment: %s. Must be development, staging, or production", cfg.Env)
	}

	// Validate site information
	if cfg.Site.Title == "" {
		return errors.New("site title cannot be empty")
	}

	if cfg.Site.Domain == "" {
		return errors.New("site domain cannot be empty")
	}

	// Validate site URL
	if !strings.HasPrefix(cfg.Site.URL, "http://") && !strings.HasPrefix(cfg.Site.URL, "https://") {
		return fmt.Errorf("invalid site URL: %s. Must start with http:// or https://", cfg.Site.URL)
	}

	// Validate email configuration in production
	if cfg.Env == "production" {
		if cfg.Email.Host == "" || cfg.Email.Port == "" || cfg.Email.User == "" || cfg.Email.Pass == "" {
			return errors.New("complete email configuration is required in production")
		}
	}

	// Validate port
	port, err := strconv.Atoi(cfg.Frontend.Port)
	if err != nil || port < 1 || port > 65535 {
		return fmt.Errorf("invalid frontend port: %s", cfg.Frontend.Port)
	}

	return nil
}
