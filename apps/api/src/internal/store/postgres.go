// Package store owns the API's connection to its Postgres tenant (ADR-051, DATA-007).
package store

import (
	"context"
	"errors"
	"sync"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// maxConns bounds this tenant's share of a server sized for few clients (256 Mi, ADR-051).
const maxConns = 5

// ErrNotConfigured means the environment gives the API no database.
var ErrNotConfigured = errors.New("postgres is not configured")

var (
	poolOnce sync.Once
	pool     *pgxpool.Pool
	poolErr  error
)

// Pool returns the process-wide pool. pgxpool connects in the background, so the API starts
// while Postgres is down, and pgx redacts the password from its parse errors.
func Pool(p config.Postgres) (*pgxpool.Pool, error) {
	if !p.Configured() {
		return nil, ErrNotConfigured
	}
	poolOnce.Do(func() { pool, poolErr = newPool(p) })
	return pool, poolErr
}

func newPool(p config.Postgres) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(p.DSN())
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = maxConns
	return pgxpool.NewWithConfig(context.Background(), cfg)
}

// Ping makes one round trip to the tenant.
func Ping(ctx context.Context, p config.Postgres) error {
	db, err := Pool(p)
	if err != nil {
		return err
	}
	return db.Ping(ctx)
}
