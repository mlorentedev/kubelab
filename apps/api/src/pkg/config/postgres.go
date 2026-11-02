package config

import (
	"net"
	"net/url"
	"os"
)

// Postgres is the API's connection to its tenant in the shared data service (ADR-051, DATA-007).
// The tenant names both the role and the database, as `provision-postgres-tenant` creates them.
type Postgres struct {
	Host     string
	Port     string
	Tenant   string
	Password string // never logged: use DSN only to open the connection
}

// loadPostgres reads the connection from the environment. Host and port are the shared infra
// names (ADR-036). INFRA_POSTGRES_DATABASE and _USERNAME are deliberately not read: they name the
// server's owner role, and the API connects as its own tenant.
func loadPostgres() Postgres {
	return Postgres{
		Host:     os.Getenv("INFRA_POSTGRES_HOST"),
		Port:     os.Getenv("INFRA_POSTGRES_PORT"),
		Tenant:   os.Getenv("POSTGRES_TENANT"),
		Password: os.Getenv("POSTGRES_TENANT_PASSWORD"),
	}
}

// Configured reports whether every part of the connection is present. An API without it still
// starts: nothing it served before DATA-007 needs a database.
func (p Postgres) Configured() bool {
	return p.Host != "" && p.Port != "" && p.Tenant != "" && p.Password != ""
}

// DSN composes the connection URL, so no URL with a password exists on disk (ADR-051 D2). TLS is
// off because the connection stays on the cluster network, behind the postgres NetworkPolicy.
func (p Postgres) DSN() string {
	u := url.URL{
		Scheme:   "postgres",
		User:     url.UserPassword(p.Tenant, p.Password),
		Host:     net.JoinHostPort(p.Host, p.Port),
		Path:     "/" + p.Tenant,
		RawQuery: "sslmode=disable",
	}
	return u.String()
}
