// Package health serves the liveness and readiness endpoints.
//
// It deliberately does not import internal/services: that package loads the
// configuration in init() and panics when it is missing, which would make
// every test of this package depend on the process environment.
package health

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// ServiceName identifies this API in health responses.
const ServiceName = "kubelab-api"

const (
	StatusAlive    = "alive"
	StatusReady    = "ready"
	StatusDegraded = "degraded"
	StatusUnready  = "unready"

	checkOK       = "ok"
	checkDegraded = "degraded"

	beehiivBaseURL  = "https://api.beehiiv.com"
	beehiivTimeout  = 3 * time.Second
	beehiivCacheTTL = 30 * time.Second
	postgresTimeout = 2 * time.Second
)

// Check is the outcome of one dependency probe. A check never gates readiness:
// a dependency that is down makes the API degraded, not unroutable.
type Check struct {
	Component string `json:"component"`
	Status    string `json:"status"`
	Message   string `json:"message,omitempty"`
}

// Response is the body of /ready. /health and /healthz carry only the first
// three fields.
type Response struct {
	Service   string    `json:"service"`
	Status    string    `json:"status"`
	Version   string    `json:"version,omitempty"`
	Checks    []Check   `json:"checks,omitempty"`
	Timestamp time.Time `json:"timestamp"`
}

// Handler holds the injectable dependencies of the readiness check.
type Handler struct {
	LoadConfig  func() (*config.Config, error)
	HTTPClient  *http.Client
	BeehiivBase string
	Now         func() time.Time
	// PingPostgres makes a round trip to the API's tenant. Nil means no database is wired.
	PingPostgres func(ctx context.Context, conf *config.Config) error

	mu         sync.Mutex
	cached     Check
	cachedAt   time.Time
	cacheValid bool
	refreshing bool
}

// New returns a Handler wired to the real configuration and the Beehiiv API.
func New() *Handler {
	return &Handler{
		LoadConfig:  config.GetConfig,
		HTTPClient:  &http.Client{Timeout: beehiivTimeout},
		BeehiivBase: beehiivBaseURL,
		Now:         time.Now,
		PingPostgres: func(ctx context.Context, conf *config.Config) error {
			return store.Ping(ctx, conf.Postgres)
		},
	}
}

// Register mounts the three probe routes.
func (h *Handler) Register(r gin.IRoutes) {
	r.GET("/health", h.Live)
	r.GET("/healthz", h.Live)
	r.GET("/ready", h.Ready)
}

// Live answers 200 as long as the process can serve a request. It touches no
// dependency: a liveness probe that fails because Beehiiv is down restarts a
// healthy pod.
func (h *Handler) Live(c *gin.Context) {
	c.JSON(http.StatusOK, Response{
		Service:   ServiceName,
		Status:    StatusAlive,
		Timestamp: h.Now(),
	})
}

// Ready answers 503 only when the API cannot do its job at all (its
// configuration does not load). Beehiiv and email problems are reported as
// degraded with a 200, so a third-party outage never pulls the pod out of
// rotation.
func (h *Handler) Ready(c *gin.Context) {
	resp := Response{Service: ServiceName, Timestamp: h.Now()}

	conf, err := h.LoadConfig()
	if err != nil || conf == nil {
		resp.Status = StatusUnready
		resp.Checks = []Check{{Component: "config", Status: "failed", Message: "configuration does not load"}}
		c.JSON(http.StatusServiceUnavailable, resp)
		return
	}

	resp.Version = conf.Version
	resp.Checks = []Check{
		h.beehiivCheck(c.Request.Context(), conf),
		emailCheck(conf),
	}
	if ck, ok := h.postgresCheck(c.Request.Context(), conf); ok {
		resp.Checks = append(resp.Checks, ck)
	}
	resp.Status = StatusReady
	for _, ck := range resp.Checks {
		if ck.Status != checkOK {
			resp.Status = StatusDegraded
			break
		}
	}
	c.JSON(http.StatusOK, resp)
}

func emailCheck(conf *config.Config) Check {
	if conf.Email.Host == "" || conf.Email.User == "" || conf.Email.Pass == "" {
		return Check{Component: "email", Status: checkDegraded, Message: "incomplete email configuration"}
	}
	return Check{Component: "email", Status: checkOK}
}

// postgresCheck reports the database only where the API is configured to use one, so an
// environment that has not received the tenant yet is not reported degraded. Like every check it
// never gates readiness: the routes that serve without a database keep serving. The message says
// nothing about the cause, because a driver error can carry the connection's details.
func (h *Handler) postgresCheck(ctx context.Context, conf *config.Config) (Check, bool) {
	if h.PingPostgres == nil || !conf.Postgres.Configured() {
		return Check{}, false
	}
	ctx, cancel := context.WithTimeout(ctx, postgresTimeout)
	defer cancel()
	if err := h.PingPostgres(ctx, conf); err != nil {
		return Check{Component: "postgres", Status: checkDegraded, Message: "postgres unreachable"}, true
	}
	return Check{Component: "postgres", Status: checkOK}, true
}

// beehiivCheck makes a real authenticated round trip, cached for
// beehiivCacheTTL so a probe every few seconds does not become a request every
// few seconds against a rate-limited third party. The lock guards only the
// cache: one caller refreshes an expired entry while the others answer from the
// stale one at once, so a slow Beehiiv never queues probes behind its timeout.
func (h *Handler) beehiivCheck(ctx context.Context, conf *config.Config) Check {
	h.mu.Lock()
	if h.cacheValid && h.Now().Sub(h.cachedAt) < beehiivCacheTTL {
		ck := h.cached
		h.mu.Unlock()
		return ck
	}
	if h.refreshing {
		ck := h.cached
		valid := h.cacheValid
		h.mu.Unlock()
		if valid {
			return ck
		}
		return Check{Component: "beehiiv", Status: checkDegraded, Message: "first check in progress"}
	}
	h.refreshing = true
	h.mu.Unlock()

	// The verdict is shared for the whole TTL, so it must describe Beehiiv, not
	// the caller's patience: a prober that hangs up mid-request would otherwise
	// cache its own cancellation as "beehiiv unreachable" for every other prober.
	// probeBeehiiv still bounds the call with beehiivTimeout.
	ck := h.probeBeehiiv(context.WithoutCancel(ctx), conf)

	h.mu.Lock()
	h.cached, h.cachedAt, h.cacheValid, h.refreshing = ck, h.Now(), true, false
	h.mu.Unlock()
	return ck
}

func (h *Handler) probeBeehiiv(ctx context.Context, conf *config.Config) Check {
	degraded := func(msg string) Check {
		return Check{Component: "beehiiv", Status: checkDegraded, Message: msg}
	}
	if conf.Beehiiv.APIKey == "" || conf.Beehiiv.PubID == "" {
		return degraded("beehiiv credentials not configured")
	}

	ctx, cancel := context.WithTimeout(ctx, beehiivTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		h.BeehiivBase+"/v2/publications/"+conf.Beehiiv.PubID, nil)
	if err != nil {
		return degraded("cannot build request")
	}
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	resp, err := h.HTTPClient.Do(req)
	if err != nil {
		return degraded("beehiiv unreachable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return degraded("beehiiv answered " + http.StatusText(resp.StatusCode))
	}
	return Check{Component: "beehiiv", Status: checkOK}
}
