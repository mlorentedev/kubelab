package forge_test

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

func genKey(t *testing.T) (*rsa.PrivateKey, string) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	block := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	return key, string(block)
}

func TestAppTokensSignsAndCaches(t *testing.T) {
	key, keyPEM := genKey(t)
	now := time.Date(2026, 11, 2, 8, 0, 0, 0, time.UTC)
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != http.MethodPost || r.URL.Path != "/app/installations/77/access_tokens" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		parts := strings.Split(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), ".")
		if len(parts) != 3 {
			t.Fatalf("not a jwt: %d parts", len(parts))
		}
		digest := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
		sig, _ := base64.RawURLEncoding.DecodeString(parts[2])
		if err := rsa.VerifyPKCS1v15(&key.PublicKey, crypto.SHA256, digest[:], sig); err != nil {
			t.Errorf("signature: %v", err)
		}
		raw, _ := base64.RawURLEncoding.DecodeString(parts[1])
		var claims map[string]int64
		if err := json.Unmarshal(raw, &claims); err != nil {
			t.Fatal(err)
		}
		if claims["iss"] != 42 || claims["exp"]-claims["iat"] > 600 {
			t.Errorf("claims = %v", claims)
		}
		w.WriteHeader(http.StatusCreated)
		fmt.Fprintf(w, `{"token":"tok-%d","expires_at":%q}`, calls, now.Add(time.Hour).Format(time.RFC3339))
	}))
	defer srv.Close()

	current := now
	a := &forge.AppTokens{BaseURL: srv.URL, AppID: "42", InstallationID: "77", PrivateKeyPEM: keyPEM,
		HTTP: srv.Client(), Now: func() time.Time { return current }}

	for i := 0; i < 2; i++ {
		got, err := a.Token(context.Background())
		if err != nil || got != "tok-1" {
			t.Fatalf("read %d: %q, %v", i, got, err)
		}
	}
	current = now.Add(56 * time.Minute) // inside the refresh margin
	got, err := a.Token(context.Background())
	if err != nil || got != "tok-2" {
		t.Fatalf("after margin: %q, %v", got, err)
	}
	if calls != 2 {
		t.Fatalf("exchanges = %d, want 2", calls)
	}
}

func TestAppTokensRefusalsLeakNothing(t *testing.T) {
	_, keyPEM := genKey(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	}))
	defer srv.Close()

	cases := map[string]*forge.AppTokens{
		"bad pem":    {BaseURL: srv.URL, AppID: "42", InstallationID: "1", PrivateKeyPEM: "secret-material"},
		"bad app id": {BaseURL: srv.URL, AppID: "x", InstallationID: "1", PrivateKeyPEM: keyPEM},
		"refused":    {BaseURL: srv.URL, AppID: "42", InstallationID: "1", PrivateKeyPEM: keyPEM},
	}
	for name, a := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := a.Token(context.Background())
			if err == nil {
				t.Fatal("want an error")
			}
			if strings.Contains(err.Error(), "secret-material") {
				t.Fatalf("key material in error: %v", err)
			}
		})
	}
}

func TestGitHubTokensFailureIsUnreachable(t *testing.T) {
	g := &forge.GitHub{BaseURL: "http://127.0.0.1:1", Tokens: func(context.Context) (string, error) {
		return "", fmt.Errorf("no token")
	}}
	src := forge.Source{Forge: "github", Owner: "o", Repo: "r"}
	_, err := g.ListItems(context.Background(), src, time.Time{})
	var se *forge.SourceError
	if !errors.As(err, &se) {
		t.Fatalf("err = %v, want SourceError", err)
	}
}
