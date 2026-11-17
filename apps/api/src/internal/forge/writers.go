package forge

import "net/http"

// githubAPI is GitHub's API root, shared by the reader and the writer.
const githubAPI = "https://api.github.com"

// NewWriters builds one writer per forge the environment can write to, each behind its own
// hourly call ceiling, apart from the readers': a reconcile that spends the readers' hour never
// refuses an operator's write. A forge with no credential has no writer, and WriterFor says so
// with ErrNoWriter; nothing is built to send an anonymous write.
//
// GitHub writes through the App installation, so it needs the App key. Gitea needs its address and
// its own write token: the reader's token is read:issue, and is never lent to a write. Staging has
// no write token (ADR-066 W7), so it has no Gitea writer.
func NewWriters(c Credentials) map[string]Writer {
	writers := map[string]Writer{}
	if c.GitHubPrivateKey != "" {
		client := &http.Client{Transport: &Ceiling{Limit: HourlyCallCeiling}}
		writers["github"] = &GitHubWriter{BaseURL: githubAPI, Tokens: newAppTokens(c, client).Token, HTTP: client}
	}
	if c.GiteaURL != "" && c.GiteaWriteToken != "" {
		writers["gitea"] = &GiteaWriter{
			BaseURL: c.GiteaURL,
			Token:   c.GiteaWriteToken,
			HTTP:    &http.Client{Transport: &Ceiling{Limit: HourlyCallCeiling}},
		}
	}
	return writers
}
