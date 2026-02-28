package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
)

// Environment constants
const (
	EnvDev     = "dev"
	EnvStaging = "staging"
	EnvProd    = "prod"
)

// Config represents the complete application configuration
type Config struct {
	Environment string
	Version     string
	Host        string
	Port        string
	Site        struct {
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
}

var config *Config

// GetConfig retrieves the global configuration from Environment Variables
func GetConfig() (*Config, error) {
	// Return cached config if it exists
	if config != nil {
		return config, nil
	}

	cfg, err := populateConfig()
	if err != nil {
		return nil, err
	}

	config = cfg
	return config, nil
}

// populateConfig fills the configuration struct with environment variables
func populateConfig() (*Config, error) {
	cfg := &Config{}

	// Environment and Version
	cfg.Environment = os.Getenv("ENVIRONMENT")
	cfg.Version = os.Getenv("VERSION")
	cfg.Host = os.Getenv("HOST")
	cfg.Port = os.Getenv("PORT")

	// Default to dev if empty (Safe fallback)
	if cfg.Environment == "" {
		// Strict check: Fail if environment is not set (managed by infra)
		// return nil, errors.New("ENVIRONMENT variable is required")
		// Loose check for local execution without toolkit:
		cfg.Environment = EnvDev
	}

	// Site Configuration
	cfg.Site.Title = os.Getenv("SITE_TITLE")
	cfg.Site.Author = os.Getenv("SITE_AUTHOR")
	cfg.Site.Domain = os.Getenv("SITE_DOMAIN")
	cfg.Site.Mail = os.Getenv("SITE_MAIL")
	cfg.Site.URL = constructSiteURL(cfg)

	// Beehiiv Configuration
	cfg.Beehiiv.APIKey = os.Getenv("BEEHIIV_API_KEY")
	cfg.Beehiiv.PubID = os.Getenv("BEEHIIV_PUB_ID")

	// Email Configuration
	cfg.Email.Host = os.Getenv("EMAIL_HOST")
	cfg.Email.Port = os.Getenv("EMAIL_PORT")
	cfg.Email.From = os.Getenv("EMAIL_FROM")
	cfg.Email.User = os.Getenv("EMAIL_USER")
	cfg.Email.Pass = os.Getenv("EMAIL_PASS")
	cfg.Email.Secure = getBoolEnv("EMAIL_SECURE", true)

	// Validate configuration
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}

	return cfg, nil
}

// constructSiteURL builds the site URL based on environment and configuration
func constructSiteURL(cfg *Config) string {
	if url := os.Getenv("SITE_URL"); url != "" {
		return url
	}

	if cfg.Environment == EnvProd {
		return fmt.Sprintf("https://%s", cfg.Site.Domain)
	}

	return fmt.Sprintf("http://%s:%s", cfg.Host, cfg.Port)
}

// getBoolEnv parses a boolean environment variable
func getBoolEnv(key string, defaultValue bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}
	boolValue, err := strconv.ParseBool(value)
	if err != nil {
		return defaultValue
	}
	return boolValue
}

// validateConfig checks the configuration for completeness and correctness
func validateConfig(cfg *Config) error {
	if cfg.Environment != EnvDev && cfg.Environment != EnvStaging && cfg.Environment != EnvProd {
		return fmt.Errorf("invalid environment: %s. Must be %s, %s, or %s", cfg.Environment, EnvDev, EnvStaging, EnvProd)
	}

	if cfg.Site.Title == "" {
		return errors.New("SITE_TITLE is required")
	}

	// Production strict checks
	if cfg.Environment == EnvProd {
		if cfg.Site.Domain == "" {
			return errors.New("SITE_DOMAIN is required in production")
		}
		if cfg.Email.Host == "" || cfg.Email.User == "" || cfg.Email.Pass == "" {
			return errors.New("email credentials (EMAIL_HOST, USER, PASS) are required in production")
		}
	}

	return nil
}
