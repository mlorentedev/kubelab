// Package store owns the API's connection to its Postgres tenant (ADR-051, DATA-007).
package store

import (
	"context"
	"errors"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
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

// StoreEvent keeps a verified webhook delivery. The primary key on (forge, delivery_id)
// turns a redelivery into a no-op, which is what makes it project once.
func StoreEvent(ctx context.Context, p config.Postgres, forgeName, deliveryID, eventType string, payload []byte) error {
	db, err := Pool(p)
	if err != nil {
		return err
	}
	_, err = db.Exec(ctx, `INSERT INTO forge_event (forge, delivery_id, event_type, payload)
		VALUES ($1, $2, $3, $4) ON CONFLICT (forge, delivery_id) DO NOTHING`,
		forgeName, deliveryID, eventType, string(payload))
	return err
}

// ForgeModel is the read model on Postgres.
type ForgeModel struct{ Conf config.Postgres }

// LastRead returns the zero time for a source never read.
func (m ForgeModel) LastRead(ctx context.Context, src forge.Source) (time.Time, error) {
	db, err := Pool(m.Conf)
	if err != nil {
		return time.Time{}, err
	}
	var asOf *time.Time
	err = db.QueryRow(ctx, `SELECT as_of FROM forge_source WHERE forge = $1 AND owner = $2 AND repo = $3`,
		src.Forge, src.Owner, src.Repo).Scan(&asOf)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && asOf == nil) {
		return time.Time{}, nil
	}
	if err != nil {
		return time.Time{}, err
	}
	return *asOf, nil
}

// SaveRead writes the source row first, because forge_item holds a foreign key to it.
func (m ForgeModel) SaveRead(ctx context.Context, src forge.Source, items []forge.Item, asOf time.Time) error {
	db, err := Pool(m.Conf)
	if err != nil {
		return err
	}
	return pgx.BeginFunc(ctx, db, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `INSERT INTO forge_source (forge, owner, repo, as_of, source_reachable, last_attempt_at)
			VALUES ($1, $2, $3, $4, true, $4)
			ON CONFLICT (forge, owner, repo) DO UPDATE
			SET as_of = $4, source_reachable = true, last_attempt_at = $4`,
			src.Forge, src.Owner, src.Repo, asOf); err != nil {
			return err
		}
		for _, it := range items {
			if _, err := tx.Exec(ctx, `INSERT INTO forge_item
				(forge, owner, repo, number, kind, title, state, author, assignees, labels, url, updated_at)
				VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
				ON CONFLICT (forge, owner, repo, number) DO UPDATE SET
				kind = $5, title = $6, state = $7, author = $8, assignees = $9, labels = $10, url = $11, updated_at = $12`,
				src.Forge, src.Owner, src.Repo, it.Number, string(it.Kind), it.Title, it.State, it.Author,
				nonNil(it.Assignees), nonNil(it.Labels), it.URL, it.UpdatedAt); err != nil {
				return err
			}
		}
		return nil
	})
}

// MarkUnreachable keeps as_of, so the source still shows when it was last read.
func (m ForgeModel) MarkUnreachable(ctx context.Context, src forge.Source, at time.Time) error {
	db, err := Pool(m.Conf)
	if err != nil {
		return err
	}
	_, err = db.Exec(ctx, `INSERT INTO forge_source (forge, owner, repo, source_reachable, last_attempt_at)
		VALUES ($1, $2, $3, false, $4)
		ON CONFLICT (forge, owner, repo) DO UPDATE SET source_reachable = false, last_attempt_at = $4`,
		src.Forge, src.Owner, src.Repo, at)
	return err
}

// Pending returns deliveries not yet projected, oldest first.
func (m ForgeModel) Pending(ctx context.Context, limit int) ([]forge.Event, error) {
	db, err := Pool(m.Conf)
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT forge, delivery_id, event_type, payload::text FROM forge_event
		WHERE projected_at IS NULL ORDER BY received_at LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var events []forge.Event
	for rows.Next() {
		var e forge.Event
		var payload string
		if err := rows.Scan(&e.Forge, &e.DeliveryID, &e.Type, &payload); err != nil {
			return nil, err
		}
		e.Payload = []byte(payload)
		events = append(events, e)
	}
	return events, rows.Err()
}

// Project writes the item and marks the delivery in one transaction. The source row comes
// first because of the foreign key, with no as_of: only a full read moves that. An older
// delivery arriving late does not overwrite a newer read of the same item.
func (m ForgeModel) Project(ctx context.Context, e forge.Event, item *forge.Item) error {
	db, err := Pool(m.Conf)
	if err != nil {
		return err
	}
	return pgx.BeginFunc(ctx, db, func(tx pgx.Tx) error {
		if item != nil {
			src := item.Source
			if _, err := tx.Exec(ctx, `INSERT INTO forge_source (forge, owner, repo) VALUES ($1, $2, $3)
				ON CONFLICT (forge, owner, repo) DO NOTHING`, src.Forge, src.Owner, src.Repo); err != nil {
				return err
			}
			if _, err := tx.Exec(ctx, `INSERT INTO forge_item
				(forge, owner, repo, number, kind, title, state, author, assignees, labels, url, updated_at)
				VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
				ON CONFLICT (forge, owner, repo, number) DO UPDATE SET
				kind = $5, title = $6, state = $7, author = $8, assignees = $9, labels = $10, url = $11, updated_at = $12
				WHERE forge_item.updated_at <= $12`,
				src.Forge, src.Owner, src.Repo, item.Number, string(item.Kind), item.Title, item.State, item.Author,
				nonNil(item.Assignees), nonNil(item.Labels), item.URL, item.UpdatedAt); err != nil {
				return err
			}
		}
		_, err := tx.Exec(ctx, `UPDATE forge_event SET projected_at = now()
			WHERE forge = $1 AND delivery_id = $2 AND projected_at IS NULL`, e.Forge, e.DeliveryID)
		return err
	})
}

func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}
