package api

import (
	"context"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// The gate reaches the runtime: the same credentials give a view with writers when the
// environment declares writes and none when it does not (ADR-066 W14), so staging, which holds
// the App key for its reads, builds nothing a route or the worker could send with.
func TestTheViewHasWritersOnlyWhenTheEnvironmentDeclaresWrites(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		conf := &config.Config{}
		conf.Forge.GitHubAppID, conf.Forge.GitHubInstallationID, conf.Forge.GitHubPrivateKey = "1", "2", "pem"
		conf.Forge.GiteaURL, conf.Forge.GiteaToken, conf.Forge.GiteaWriteToken = "http://gitea:3000", "r", "w"
		conf.Forge.WritesEnabled = enabled
		view := NewForgeView(context.Background(), conf)
		if enabled && len(view.Writers) != 2 {
			t.Errorf("writes enabled: %d writers, want github and gitea", len(view.Writers))
		}
		if !enabled && len(view.Writers) != 0 {
			t.Errorf("writes not enabled: %d writers were built", len(view.Writers))
		}
	}
}
