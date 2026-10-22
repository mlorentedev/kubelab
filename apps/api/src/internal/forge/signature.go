package forge

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

// VerifySignature checks a webhook body against the signature header the forge
// sent. GitHub (X-Hub-Signature-256) prefixes the hex digest with "sha256=";
// Gitea (X-Gitea-Signature) sends it bare. An empty secret never verifies, so
// a receiver with no secret configured rejects everything instead of accepting
// everything. The comparison is constant-time.
func VerifySignature(forgeName, secret, header string, body []byte) bool {
	if secret == "" || header == "" {
		return false
	}
	digest := header
	switch forgeName {
	case "github":
		var ok bool
		if digest, ok = strings.CutPrefix(header, "sha256="); !ok {
			return false
		}
	case "gitea":
	default:
		return false
	}
	got, err := hex.DecodeString(digest)
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return hmac.Equal(got, mac.Sum(nil))
}
