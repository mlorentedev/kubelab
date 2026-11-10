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
	GiteaToken           string
}

// NewReaders builds one reader per forge the environment can reach, each behind
// its own hourly call ceiling: the ceiling is per forge (AC4), so GitHub's calls
// never spend Gitea's hour. Gitea is wired only when its address is declared;
// without one a gitea: source reads as unreachable ("no reader for this forge").
func NewReaders(c Credentials) map[string]Reader {
	client := &http.Client{Transport: &Ceiling{Limit: HourlyCallCeiling}}
	github := &GitHub{BaseURL: "https://api.github.com", HTTP: client}
	if c.GitHubPrivateKey != "" {
		tokens := &AppTokens{
			BaseURL:        github.BaseURL,
			AppID:          c.GitHubAppID,
			InstallationID: c.GitHubInstallationID,
			PrivateKeyPEM:  c.GitHubPrivateKey,
			HTTP:           client,
		}
		github.Tokens = tokens.Token
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
