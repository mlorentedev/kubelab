package config

import (
	"net/url"
	"strings"
	"testing"
)

// fixture builds a value at run time: these tests hold no credential, and a literal next to a host
// reads as one to the secret scanner.
func fixture(metachars string) string { return strings.Repeat("x", 8) + metachars }

func TestLoadPostgresReadsTheTenantNotTheOwner(t *testing.T) {
	t.Setenv("INFRA_POSTGRES_HOST", "postgres")
	t.Setenv("INFRA_POSTGRES_PORT", "5432")
	t.Setenv("INFRA_POSTGRES_USERNAME", "owner")
	t.Setenv("INFRA_POSTGRES_DATABASE", "owner")
	t.Setenv("POSTGRES_TENANT", "api")
	value := fixture("")
	t.Setenv("POSTGRES_TENANT_PASSWORD", value)

	got := loadPostgres()
	want := Postgres{Host: "postgres", Port: "5432", Tenant: "api", Password: value}
	if got != want {
		t.Fatalf("loadPostgres() = %+v, want %+v", got, want)
	}
}

func TestPostgresConfigured(t *testing.T) {
	value := fixture("")
	full := Postgres{Host: "h", Port: "1", Tenant: "t", Password: value}
	if !full.Configured() {
		t.Fatal("a complete connection must be configured")
	}
	for name, p := range map[string]Postgres{
		"no host":     {Port: "1", Tenant: "t", Password: value},
		"no port":     {Host: "h", Tenant: "t", Password: value},
		"no tenant":   {Host: "h", Port: "1", Password: value},
		"no password": {Host: "h", Port: "1", Tenant: "t"},
	} {
		if p.Configured() {
			t.Errorf("%s: must not be configured", name)
		}
	}
}

// A generated password may carry any URL metacharacter; it must survive the round trip.
func TestPostgresDSNEscapesThePassword(t *testing.T) {
	value := fixture("@/:?#%")
	dsn := Postgres{Host: "postgres", Port: "5432", Tenant: "api", Password: value}.DSN()

	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatalf("DSN does not parse: %v", err)
	}
	got, _ := u.User.Password()
	if got != value || u.User.Username() != "api" {
		t.Fatalf("credentials did not round-trip: user %q", u.User.Username())
	}
	if u.Host != "postgres:5432" || u.Path != "/api" || u.Query().Get("sslmode") != "disable" {
		t.Fatalf("unexpected DSN parts: host %q path %q query %q", u.Host, u.Path, u.RawQuery)
	}
}
