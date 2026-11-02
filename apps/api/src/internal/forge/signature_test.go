package forge_test

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

func sign(secret, body string) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write([]byte(body))
	return hex.EncodeToString(m.Sum(nil))
}

func TestVerifySignature(t *testing.T) {
	const secret, body = "s3cret", `{"action":"opened"}`
	good := sign(secret, body)

	cases := []struct {
		name   string
		forge  string
		header string
		secret string
		body   string
		ok     bool
	}{
		{"github accepts sha256= prefix", "github", "sha256=" + good, secret, body, true},
		{"gitea accepts bare hex", "gitea", good, secret, body, true},
		{"github rejects a bare hex", "github", good, secret, body, false},
		{"github rejects a wrong secret", "github", "sha256=" + sign("other", body), secret, body, false},
		{"gitea rejects a tampered body", "gitea", good, secret, body + " ", false},
		{"missing header is rejected", "github", "", secret, body, false},
		{"non-hex header is rejected", "gitea", "zz", secret, body, false},
		{"an empty secret rejects even a matching signature", "gitea", sign("", body), "", body, false},
		{"unknown forge is rejected", "gitlab", good, secret, body, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := forge.VerifySignature(c.forge, c.secret, c.header, []byte(c.body)); got != c.ok {
				t.Fatalf("got %v, want %v", got, c.ok)
			}
		})
	}
}
