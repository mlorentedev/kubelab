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

// TestPopulateConfigForge pins the forge credentials' names and that none of them is required:
// the Deployment injects them from api-secrets and the ConfigMap, and staging has no Gitea token.
func TestPopulateConfigForge(t *testing.T) {
	t.Setenv("SITE_TITLE", "KubeLab")
	t.Setenv("SITE_DOMAIN", "kubelab.live")

	t.Run("absent", func(t *testing.T) {
		for _, key := range []string{
			"FORGE_GITEA_TOKEN", "FORGE_GITEA_WRITE_TOKEN", "INFRA_FORGE_GITEA_URL", "INFRA_FORGE_GITHUB_APP_ID",
			"INFRA_FORGE_GITHUB_INSTALLATION_ID", "FORGE_GITHUB_PRIVATE_KEY", "FORGE_CREATE_TOKEN",
			"INFRA_FORGE_WRITES_ENABLED",
		} {
			t.Setenv(key, "")
		}
		cfg, err := populateConfig()
		if err != nil {
			t.Fatalf("populateConfig() without forge credentials failed: %v", err)
		}
		if cfg.Forge.GiteaToken != "" || cfg.Forge.GiteaWriteToken != "" || cfg.Forge.GiteaURL != "" || cfg.Forge.GitHubPrivateKey != "" ||
			cfg.Forge.GitHubAppID != "" || cfg.Forge.GitHubInstallationID != "" || cfg.Forge.CreateToken != "" || cfg.Forge.WritesEnabled {
			t.Fatalf("absent credentials must stay empty, got %+v", cfg.Forge)
		}
	})

	t.Run("present", func(t *testing.T) {
		t.Setenv("FORGE_GITEA_TOKEN", "gitea-token")
		t.Setenv("FORGE_GITEA_WRITE_TOKEN", "gitea-write-token")
		t.Setenv("INFRA_FORGE_GITEA_URL", "http://gitea:3000")
		t.Setenv("INFRA_FORGE_GITHUB_APP_ID", "1")
		t.Setenv("INFRA_FORGE_GITHUB_INSTALLATION_ID", "2")
		t.Setenv("FORGE_GITHUB_PRIVATE_KEY", "pem-body")
		t.Setenv("FORGE_CREATE_TOKEN", "machine-token")
		cfg, err := populateConfig()
		if err != nil {
			t.Fatalf("populateConfig() with forge credentials failed: %v", err)
		}
		want := "http://gitea:3000|gitea-token|gitea-write-token|1|2|pem-body|machine-token"
		got := cfg.Forge.GiteaURL + "|" + cfg.Forge.GiteaToken + "|" + cfg.Forge.GiteaWriteToken + "|" + cfg.Forge.GitHubAppID + "|" +
			cfg.Forge.GitHubInstallationID + "|" + cfg.Forge.GitHubPrivateKey + "|" + cfg.Forge.CreateToken
		if got != want {
			t.Fatalf("forge credentials read from the wrong variables: got %q, want %q", got, want)
		}
	})
}

// The write gate is a declaration, never inferred from a credential (ADR-066 W14): absent or
// unreadable is off, so a mistyped value fails closed and staging never writes by accident.
func TestForgeWritesEnabledFailsClosed(t *testing.T) {
	t.Setenv("ENVIRONMENT", EnvDev)
	t.Setenv("SITE_TITLE", "KubeLab")
	t.Setenv("SITE_DOMAIN", "kubelab.live")
	// Credentials that would build a writer must change nothing while the gate is off.
	t.Setenv("FORGE_GITEA_WRITE_TOKEN", "gitea-write-token")
	t.Setenv("FORGE_GITHUB_PRIVATE_KEY", "pem-body")
	for value, want := range map[string]bool{
		"": false, "false": false, "no": false, "enabled": false, "tru": false, " true": false,
		"true": true, "True": true, "1": true,
	} {
		t.Setenv("INFRA_FORGE_WRITES_ENABLED", value)
		cfg, err := populateConfig()
		if err != nil {
			t.Fatal(err)
		}
		if cfg.Forge.WritesEnabled != want {
			t.Errorf("INFRA_FORGE_WRITES_ENABLED=%q: WritesEnabled = %v, want %v", value, cfg.Forge.WritesEnabled, want)
		}
	}
}
