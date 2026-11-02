package forge

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
	"strconv"
	"sync"
	"time"
)

const (
	// appJWTLifetime stays under GitHub's ten-minute maximum, and appJWTBackdate
	// absorbs clock drift between the node and GitHub.
	appJWTLifetime = 9 * time.Minute
	appJWTBackdate = time.Minute
	// tokenRefreshMargin renews before expiry so a long paged read cannot start
	// with a token that dies halfway through it.
	tokenRefreshMargin = 5 * time.Minute
)

// AppTokens mints GitHub App installation tokens and caches one until shortly
// before it expires, so a reconcile spends one exchange an hour and not one a read.
type AppTokens struct {
	BaseURL        string
	AppID          string
	InstallationID string
	PrivateKeyPEM  string
	HTTP           *http.Client
	Now            func() time.Time // nil means time.Now

	mu      sync.Mutex
	token   string
	expires time.Time
}

// Token returns a cached installation token or exchanges a new one.
func (a *AppTokens) Token(ctx context.Context) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	now := a.now()
	if a.token != "" && now.Add(tokenRefreshMargin).Before(a.expires) {
		return a.token, nil
	}
	token, expires, err := a.exchange(ctx, now)
	if err != nil {
		return "", err
	}
	a.token, a.expires = token, expires
	return token, nil
}

func (a *AppTokens) now() time.Time {
	if a.Now != nil {
		return a.Now()
	}
	return time.Now()
}

func (a *AppTokens) exchange(ctx context.Context, now time.Time) (string, time.Time, error) {
	signed, err := a.jwt(now)
	if err != nil {
		return "", time.Time{}, err
	}
	endpoint := fmt.Sprintf("%s/app/installations/%s/access_tokens", a.BaseURL, a.InstallationID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, nil)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("build token request: %w", err)
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("Authorization", "Bearer "+signed)
	client := a.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("exchange installation token: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		return "", time.Time{}, fmt.Errorf("exchange installation token: status %d", resp.StatusCode)
	}
	var body struct {
		Token     string    `json:"token"`
		ExpiresAt time.Time `json:"expires_at"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return "", time.Time{}, fmt.Errorf("decode installation token: %w", err)
	}
	if body.Token == "" {
		return "", time.Time{}, errors.New("exchange installation token: empty token")
	}
	return body.Token, body.ExpiresAt, nil
}

// jwt signs the RS256 token that identifies the App itself.
func (a *AppTokens) jwt(now time.Time) (string, error) {
	key, err := parseRSAKey(a.PrivateKeyPEM)
	if err != nil {
		return "", err
	}
	appID, err := strconv.ParseInt(a.AppID, 10, 64)
	if err != nil {
		return "", errors.New("github app id is not a number")
	}
	header, err := json.Marshal(map[string]string{"alg": "RS256", "typ": "JWT"})
	if err != nil {
		return "", err
	}
	claims, err := json.Marshal(map[string]int64{
		"iat": now.Add(-appJWTBackdate).Unix(),
		"exp": now.Add(appJWTLifetime).Unix(),
		"iss": appID,
	})
	if err != nil {
		return "", err
	}
	enc := base64.RawURLEncoding
	unsigned := enc.EncodeToString(header) + "." + enc.EncodeToString(claims)
	digest := sha256.Sum256([]byte(unsigned))
	sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, digest[:])
	if err != nil {
		return "", fmt.Errorf("sign app jwt: %w", err)
	}
	return unsigned + "." + enc.EncodeToString(sig), nil
}

// parseRSAKey never wraps the parser's error text, so nothing about the key
// can reach a log line. GitHub issues PKCS#1; PKCS#8 is what a conversion yields.
func parseRSAKey(data string) (*rsa.PrivateKey, error) {
	block, _ := pem.Decode([]byte(data))
	if block == nil {
		return nil, errors.New("github app key is not PEM")
	}
	if key, err := x509.ParsePKCS1PrivateKey(block.Bytes); err == nil {
		return key, nil
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, errors.New("github app key is not a private key")
	}
	key, ok := parsed.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("github app key is not RSA")
	}
	return key, nil
}
