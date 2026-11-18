package forge

import "net/http"

// Credentials is what NewReaders needs from the environment. Every field may be
// empty: a forge with no credential still gets a reader, and a source it cannot
// read is reported unreachable.
type Credentials struct {
	GitHubAppID          string
	GitHubInstallationID string
	GitHubPrivateKey     string // PEM; empty reads GitHub anonymously
	GiteaURL             string // the Gitea root; empty wires no Gitea reader
	GiteaToken           string // read:issue, the reader's
	GiteaWriteToken      string // write:issue, the writer's; empty wires no Gitea writer
	// WritesEnabled is the environment's explicit declaration that it may write to a forge
	// (infra.forge.writes_enabled). False builds no writer for any forge, whatever credentials
	// are present: staging holds the App key for its reads and must never write (ADR-066 W14).
	WritesEnabled bool
}

// NewReaders builds one reader per forge the environment can reach, each behind
// its own hourly call ceiling: the ceiling is per forge (AC4), so GitHub's calls
// never spend Gitea's hour. Gitea is wired only when its address is declared;
// without one a gitea: source reads as unreachable ("no reader for this forge").
func NewReaders(c Credentials) map[string]Reader {
	client := &http.Client{Transport: &Ceiling{Limit: HourlyCallCeiling}}
	github := &GitHub{BaseURL: githubAPI, HTTP: client}
	if c.GitHubPrivateKey != "" {
		github.Tokens = newAppTokens(c, client).Token
	}
	readers := map[string]Reader{"github": github}
	if c.GiteaURL != "" {
		readers["gitea"] = &Gitea{
			BaseURL: c.GiteaURL,
			Token:   c.GiteaToken,
			HTTP:    &http.Client{Transport: &Ceiling{Limit: HourlyCallCeiling}},
		}
	}
	return readers
}

// newAppTokens is the App installation's token source, over the client whose ceiling it spends.
func newAppTokens(c Credentials, client *http.Client) *AppTokens {
	return &AppTokens{
		BaseURL:        githubAPI,
		AppID:          c.GitHubAppID,
		InstallationID: c.GitHubInstallationID,
		PrivateKeyPEM:  c.GitHubPrivateKey,
		HTTP:           client,
	}
}

// Listers picks the readers that can also list an owner's repositories. They are
// the same values, so a forge's listing and its reads spend one hourly ceiling.
func Listers(readers map[string]Reader) map[string]Lister {
	listers := map[string]Lister{}
	for name, r := range readers {
		if l, ok := r.(Lister); ok {
			listers[name] = l
		}
	}
	return listers
}
