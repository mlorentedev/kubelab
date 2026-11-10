package api

import (
	"context"
	"log"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// StartForgeReconcile starts the reconcile when the environment gives it a database
// and sources. It never stops the API from starting: a bad declaration is logged.
func StartForgeReconcile(ctx context.Context, conf *config.Config) {
	sources, err := forge.ParseSources(conf.Forge.Sources)
	if err != nil {
		log.Printf("forge reconcile not started: %v", err)
		return
	}
	if len(sources) == 0 || !conf.Postgres.Configured() {
		return
	}
	r := &forge.Reconciler{
		Readers: forge.NewReaders(forge.Credentials{
			GitHubAppID:          conf.Forge.GitHubAppID,
			GitHubInstallationID: conf.Forge.GitHubInstallationID,
			GitHubPrivateKey:     conf.Forge.GitHubPrivateKey,
			GiteaURL:             conf.Forge.GiteaURL,
			GiteaToken:           conf.Forge.GiteaToken,
		}),
		Sources: sources,
		Model:   store.ForgeModel{Conf: conf.Postgres},
	}
	go r.Run(ctx, forge.ReconcilePeriod, forge.RetryPeriod)
	projector := &forge.Projector{Log: store.ForgeModel{Conf: conf.Postgres}}
	go projector.Run(ctx, forge.ProjectPeriod)
}
