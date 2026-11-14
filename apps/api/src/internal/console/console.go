// Package console serves the forge queue page and its data (CONSOLE-004).
package console

import (
	"context"
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The console has its own host, which Authelia guards whole (CONSOLE-004 AC3).
// The same binary answers the public API host, so /console is served only to a
// request for the console's host, and to none when no host is declared: through
// api.kubelab.live it is a 404, never the page.

//go:embed console.html
var consolePage []byte

// QueueReader is the console's view of the read model.
type QueueReader interface {
	Queue(ctx context.Context, sources []forge.Source, after *forge.QueueKey, limit int) (forge.QueuePage, error)
}

// maxPage bounds one answer, and is the page size when the request names none.
const maxPage = 500

// cursor is a QueueKey as the client carries it: opaque, URL-safe, and checked
// on the way back in, since it is client input.
type cursor struct {
	UpdatedAt time.Time `json:"u"`
	Source    string    `json:"s"`
	Number    int       `json:"n"`
}

func encodeCursor(k forge.QueueKey) string {
	b, _ := json.Marshal(cursor{UpdatedAt: k.UpdatedAt, Source: k.Source.String(), Number: k.Number})
	return base64.RawURLEncoding.EncodeToString(b)
}

func decodeCursor(s string) (*forge.QueueKey, error) {
	b, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return nil, err
	}
	var c cursor
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, err
	}
	src, err := forge.ParseSources(c.Source)
	if err != nil || len(src) != 1 || src[0].Wildcard() || c.Number <= 0 {
		return nil, errors.New("not a queue cursor")
	}
	return &forge.QueueKey{UpdatedAt: c.UpdatedAt, Source: src[0], Number: c.Number}, nil
}

// pageRequest reads `after` and `limit`; an absent value takes its default.
func pageRequest(c *gin.Context) (*forge.QueueKey, int, error) {
	var after *forge.QueueKey
	if s := c.Query("after"); s != "" {
		k, err := decodeCursor(s)
		if err != nil {
			return nil, 0, err
		}
		after = k
	}
	limit := maxPage
	if s := c.Query("limit"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil || n < 1 || n > maxPage {
			return nil, 0, fmt.Errorf("limit must be 1..%d", maxPage)
		}
		limit = n
	}
	return after, limit, nil
}

type sourceView struct {
	Source    string     `json:"source"`
	AsOf      *time.Time `json:"as_of"`
	Reachable bool       `json:"reachable"`
}

type itemView struct {
	Source    string    `json:"source"`
	Number    int       `json:"number"`
	Kind      string    `json:"kind"`
	Title     string    `json:"title"`
	Author    string    `json:"author"`
	Assignees []string  `json:"assignees"`
	Labels    []string  `json:"labels"`
	URL       string    `json:"url"`
	UpdatedAt time.Time `json:"updated_at"`
}

// queueView is the answer of GET /console/queue. apps/console's fixtures and its TypeScript
// contract (src/lib/contract.ts) mirror it, and TestFixturesMatchTheQueueContract holds them to it.
// Next is the cursor of the following page, null on the last one. Total counts every open
// item of the declared sources, so the page can say "N of M".
type queueView struct {
	Sources []sourceView `json:"sources"`
	Items   []itemView   `json:"items"`
	Total   int          `json:"total"`
	Next    *string      `json:"next"`
}

// Deps returns the read model and the sources to show; a seam for tests.
type Deps func() (QueueReader, []forge.Source, error)

// Live serves the read model and the catalog the reconcile reads from, so the
// console shows exactly the sources being read, wildcards resolved. With no
// catalog (the declaration did not parse) the queue answers 503, never an empty
// page that reads as "nothing open".
func Live(model QueueReader, catalog *forge.Catalog) Deps {
	return func() (QueueReader, []forge.Source, error) {
		if catalog == nil {
			return nil, nil, errors.New("no catalog: the forge sources did not parse")
		}
		// A wildcard not listed yet is shown too: the store has no row for it, so it
		// reads unreachable and never read, rather than a forge silently missing.
		return model, append(catalog.Current(), catalog.Unresolved()...), nil
	}
}

// Usage records that `identity` opened the console at `at`, and reports whether it was
// that identity's first visit of the day (ADR-066 A8). Nil records nothing.
type Usage func(ctx context.Context, identity string, at time.Time) (bool, error)

// usageTimeout bounds the counter's write, so a slow database delays the page by at most this.
const usageTimeout = 2 * time.Second

// Register adds the console's routes, answered only for its own host.
func Register(r *gin.Engine, deps Deps, domain func() string, usage Usage) {
	g := r.Group("/console", onlyHost(domain))
	g.GET("", func(c *gin.Context) { c.Redirect(http.StatusMovedPermanently, "/console/") })
	g.GET("/", func(c *gin.Context) {
		recordUsage(c, usage)
		c.Data(http.StatusOK, "text/html; charset=utf-8", consolePage)
	})
	g.GET("/queue", func(c *gin.Context) { queueHandler(c, deps) })
	registerWrites(g)
	// The bare host opens the page until apps/console serves `/` (ADR-074 D5). A 302,
	// not a 301: browsers keep a 301 indefinitely, and `/` will become the frontend's.
	r.GET("/", onlyHost(domain), func(c *gin.Context) { c.Redirect(http.StatusFound, "/console/") })
}

// recordUsage counts the page open for the identity Authelia names in Remote-User. A request
// that names none is not counted: the host check alone can be satisfied from inside the
// cluster, and only a request that came through Authelia carries the header. A failed write
// is logged and never fails the page.
func recordUsage(c *gin.Context, usage Usage) {
	identity := strings.TrimSpace(c.GetHeader("Remote-User"))
	if usage == nil || identity == "" {
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), usageTimeout)
	defer cancel()
	first, err := usage(ctx, identity, time.Now())
	switch {
	case err != nil:
		log.Printf("console usage: record %s: %v", identity, err)
	case first:
		log.Printf("console usage: first visit of the day for %s", identity)
	}
}

// onlyHost answers 404 unless the request names the console's host. Traefik routes
// by that same Host header, so a request that names it went through Authelia.
func onlyHost(domain func() string) gin.HandlerFunc {
	return func(c *gin.Context) {
		want := domain()
		host := c.Request.Host
		if h, _, err := net.SplitHostPort(host); err == nil {
			host = h
		}
		if want == "" || !strings.EqualFold(host, want) {
			c.AbortWithStatus(http.StatusNotFound)
			return
		}
		c.Next()
	}
}

func queueHandler(c *gin.Context, deps Deps) {
	reader, sources, err := deps()
	if err != nil {
		log.Printf("console queue: configuration unavailable")
		c.Status(http.StatusServiceUnavailable)
		return
	}
	after, limit, err := pageRequest(c)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	out := queueView{Sources: []sourceView{}, Items: []itemView{}}
	if len(sources) > 0 {
		// One more than the page tells whether another page exists, without a count.
		page, err := reader.Queue(c.Request.Context(), sources, after, limit+1)
		if err != nil {
			log.Printf("console queue: %v", err)
			c.Status(http.StatusServiceUnavailable)
			return
		}
		items := page.Items
		if len(items) > limit {
			items = items[:limit]
			next := encodeCursor(items[limit-1].Key())
			out.Next = &next
		}
		out.Total = page.Total
		for _, st := range page.States {
			out.Sources = append(out.Sources, sourceView{Source: st.Source.String(), AsOf: st.AsOf, Reachable: st.Reachable})
		}
		for _, it := range items {
			out.Items = append(out.Items, itemView{Source: it.Source.String(), Number: it.Number, Kind: string(it.Kind),
				Title: it.Title, Author: it.Author, Assignees: it.Assignees, Labels: it.Labels, URL: it.URL,
				UpdatedAt: it.UpdatedAt})
		}
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, out)
}
