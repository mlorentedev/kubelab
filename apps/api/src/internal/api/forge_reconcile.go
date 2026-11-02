package api

import (
	"context"
	"log"
	"net/http"

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
	client := &http.Client{Transport: &forge.Ceiling{Limit: forge.HourlyCallCeiling}}
	github := &forge.GitHub{BaseURL: "https://api.github.com", HTTP: client}
	if conf.Forge.GitHubPrivateKey != "" {
		tokens := &forge.AppTokens{
			BaseURL:        github.BaseURL,
			AppID:          conf.Forge.GitHubAppID,
			InstallationID: conf.Forge.GitHubInstallationID,
			PrivateKeyPEM:  conf.Forge.GitHubPrivateKey,
			HTTP:           client,
		}
		github.Tokens = tokens.Token
	}
	r := &forge.Reconciler{
		Readers: map[string]forge.Reader{"github": github},
		Sources: sources,
		Model:   store.ForgeModel{Conf: conf.Postgres},
	}
	go r.Run(ctx, forge.ReconcilePeriod)
}
