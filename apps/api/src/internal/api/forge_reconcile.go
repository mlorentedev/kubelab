package api

import (
	"context"
	"log"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// ForgeView is the forge view's runtime: one reader per forge, and the catalog
// that both the reconcile and the console read, so the page shows exactly the
// sources being read. Catalog is nil when the declaration does not parse.
type ForgeView struct {
	Readers map[string]forge.Reader
	Catalog *forge.Catalog
	Model   store.ForgeModel
	// CreateToken is the machine token the create accepts (AC3); empty accepts nobody.
	CreateToken string
	// ConsoleDomain is the console.s own host; empty serves the console nowhere.
	ConsoleDomain string
}

// seedTimeout bounds the start-up read of the sources already stored.
const seedTimeout = 5 * time.Second

// NewForgeView builds the readers once: a forge's listing and its reads then
// share one hourly ceiling (AC4). The catalog is seeded from the store, so a pod
// that cannot list its forge at start still shows what it read before (AC1). A
// seed that fails here is retried by the reconcile (#3247).
func NewForgeView(ctx context.Context, conf *config.Config) *ForgeView {
	readers := forge.NewReaders(forge.Credentials{
		GitHubAppID:          conf.Forge.GitHubAppID,
		GitHubInstallationID: conf.Forge.GitHubInstallationID,
		GitHubPrivateKey:     conf.Forge.GitHubPrivateKey,
		GiteaURL:             conf.Forge.GiteaURL,
		GiteaToken:           conf.Forge.GiteaToken,
	})
	view := &ForgeView{Readers: readers, Model: store.ForgeModel{Conf: conf.Postgres}, CreateToken: conf.Forge.CreateToken, ConsoleDomain: conf.Forge.ConsoleDomain}
	declared, err := forge.ParseSources(conf.Forge.Sources)
	if err != nil {
		log.Printf("forge view: sources: %v", err)
		return view
	}
	view.Catalog = &forge.Catalog{Declared: declared, Listers: forge.Listers(readers)}
	if conf.Postgres.Configured() {
		seedCtx, cancel := context.WithTimeout(ctx, seedTimeout)
		defer cancel()
		known, err := view.Model.Sources(seedCtx)
		if err != nil {
			log.Printf("forge view: seed from the store: %v", err)
		}
		view.Catalog.Seed(known)
	}
	return view
}

// StartForgeReconcile starts the reconcile when the environment gives it a database
// and sources. It never stops the API from starting: a bad declaration is logged.
func StartForgeReconcile(ctx context.Context, conf *config.Config, view *ForgeView) {
	if view.Catalog == nil || len(view.Catalog.Declared) == 0 || !conf.Postgres.Configured() {
		return
	}
	r := &forge.Reconciler{Readers: view.Readers, Catalog: view.Catalog, Model: view.Model, Known: view.Model.Sources}
	go r.Run(ctx, forge.ReconcilePeriod, forge.RetryPeriod)
	projector := &forge.Projector{Log: view.Model}
	go projector.Run(ctx, forge.ProjectPeriod)
}
