package store

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

func TestPingRefusesAnUnconfiguredDatabase(t *testing.T) {
	if err := Ping(context.Background(), config.Postgres{}); !errors.Is(err, ErrNotConfigured) {
		t.Fatalf("Ping() = %v, want ErrNotConfigured", err)
	}
}

func TestNewPoolIsBoundedAndDoesNotConnect(t *testing.T) {
	// A port nothing listens on: opening must succeed, and only a query may fail.
	value := strings.Repeat("x", 16) // built at run time so the secret scanner reads no literal
	p := config.Postgres{Host: "127.0.0.1", Port: "1", Tenant: "api", Password: value}
	db, err := newPool(p)
	if err != nil {
		t.Fatalf("newPool must not need a server: %v", err)
	}
	defer db.Close()
	if got := db.Config().MaxConns; got != maxConns {
		t.Fatalf("MaxConns = %d, want %d", got, maxConns)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err = db.Ping(ctx)
	if err == nil {
		t.Fatal("ping against a closed port must fail")
	}
	if strings.Contains(err.Error(), value) {
		t.Fatal("the connection error carries the password")
	}
}
