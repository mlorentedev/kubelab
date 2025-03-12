package config

import (
	"os"
	"strconv"

	"github.com/joho/godotenv"
	"github.com/rs/zerolog/log"
)

// Config contiene todas las variables de entorno
type Config struct {
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
	Site struct {
		Domain      string
		URL         string
		Mail        string
		Title       string
		Description string
		Keywords    string
		Author      string
	}
	RRSS struct {
		Calendly     string
		BuyMeACoffee string
		Twitter      string
		YouTube      string
		GitHub       string
	}
	Analytics struct {
		GoogleID string
	}
	FeatureFlags struct {
		EnableHomelabs bool
		EnableBlog     bool
		EnableContact  bool
	}
}

var cfg *Config

// GetConfig devuelve la configuración global
func GetConfig() *Config {
	if cfg == nil {
		loadConfig()
	}
	return cfg
}

// loadConfig carga las variables de entorno de .env si existe
func loadConfig() {
	// Cargar .env si existe
	_ = godotenv.Load()

	cfg = &Config{}

	// BEEHIIV
	cfg.Beehiiv.APIKey = os.Getenv("BEEHIIV_API_KEY")
	cfg.Beehiiv.PubID = os.Getenv("BEEHIIV_PUB_ID")

	// EMAIL
	cfg.Email.Host = os.Getenv("EMAIL_HOST")
	cfg.Email.Port = os.Getenv("EMAIL_PORT")
	cfg.Email.Secure = os.Getenv("EMAIL_SECURE") == "true"
	cfg.Email.User = os.Getenv("EMAIL_USER")
	cfg.Email.Pass = os.Getenv("EMAIL_PASS")

	// SITE
	cfg.Site.Domain = os.Getenv("SITE_DOMAIN")
	cfg.Site.URL = os.Getenv("SITE_URL")
	cfg.Site.Mail = os.Getenv("SITE_MAIL")
	cfg.Site.Title = os.Getenv("SITE_TITLE")
	cfg.Site.Description = os.Getenv("SITE_DESCRIPTION")
	cfg.Site.Keywords = os.Getenv("SITE_KEYWORDS")
	cfg.Site.Author = os.Getenv("SITE_AUTHOR")

	// RRSS
	cfg.RRSS.Calendly = os.Getenv("CALENDLY_URL")
	cfg.RRSS.BuyMeACoffee = os.Getenv("BUY_ME_A_COFFEE_URL")
	cfg.RRSS.Twitter = os.Getenv("TWITTER_URL")
	cfg.RRSS.YouTube = os.Getenv("YOUTUBE_URL")
	cfg.RRSS.GitHub = os.Getenv("GITHUB_URL")

	// ANALYTICS
	cfg.Analytics.GoogleID = os.Getenv("GOOGLE_ANALYTICS_ID")

	// FEATURE FLAGS
	cfg.FeatureFlags.EnableHomelabs, _ = strconv.ParseBool(os.Getenv("ENABLE_HOMELABS"))
	cfg.FeatureFlags.EnableBlog, _ = strconv.ParseBool(os.Getenv("ENABLE_BLOG"))
	cfg.FeatureFlags.EnableContact, _ = strconv.ParseBool(os.Getenv("ENABLE_CONTACT"))

	// Validar configuración
	if !validateConfig() {
		log.Warn().Msg("La configuración no está completa. Algunas funcionalidades pueden no estar disponibles.")
	}
}

// validateConfig valida que las variables requeridas estén presentes
func validateConfig() bool {
	// En producción requerimos estas variables
	if os.Getenv("ENV") == "production" {
		if cfg.Beehiiv.APIKey == "" ||
			cfg.Beehiiv.PubID == "" ||
			cfg.Email.Host == "" ||
			cfg.Email.User == "" ||
			cfg.Email.Pass == "" {
			log.Error().Msg("Variables de entorno requeridas no están configuradas")
			return false
		}
	}
	return true
}
