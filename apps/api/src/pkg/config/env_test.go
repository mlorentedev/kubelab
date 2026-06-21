package config

import "testing"

// TestValidateConfig is the first test in the API module (CONSOLE-002 PR-0): it proves the
// `go test` harness runs in CI and locally. validateConfig is chosen deliberately — it is a pure
// function (struct in, error out) in a package with no init(), so loading its test binary cannot
// panic the way the services package does (services.init() panics when SITE_TITLE is unset).
func TestValidateConfig(t *testing.T) {
	// newValid returns a Config that passes validation for the given environment; table cases
	// mutate one field to drive a specific failure branch.
	newValid := func(env string) *Config {
		cfg := &Config{Environment: env}
		cfg.Site.Title = "KubeLab"
		cfg.Site.Domain = "kubelab.live"
		cfg.Email.Host = "smtp.example.com"
		cfg.Email.User = "operator"
		cfg.Email.Pass = "secret"
		return cfg
	}

	tests := []struct {
		name    string
		env     string
		mutate  func(*Config)
		wantErr bool
	}{
		{name: "valid dev", env: EnvDev, wantErr: false},
		{name: "valid staging", env: EnvStaging, wantErr: false},
		{name: "valid prod with smtp and domain", env: EnvProd, wantErr: false},
		{name: "invalid environment", env: "qa", wantErr: true},
		{name: "empty environment", env: "", wantErr: true},
		{name: "dev missing site title", env: EnvDev, mutate: func(c *Config) { c.Site.Title = "" }, wantErr: true},
		{name: "prod missing domain", env: EnvProd, mutate: func(c *Config) { c.Site.Domain = "" }, wantErr: true},
		{name: "prod missing smtp pass", env: EnvProd, mutate: func(c *Config) { c.Email.Pass = "" }, wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := newValid(tt.env)
			if tt.mutate != nil {
				tt.mutate(cfg)
			}
			err := validateConfig(cfg)
			if (err != nil) != tt.wantErr {
				t.Fatalf("validateConfig() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
