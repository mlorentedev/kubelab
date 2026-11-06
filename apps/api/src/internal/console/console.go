// Package console serves the forge queue page and its data (CONSOLE-004).
package console

import (
	"context"
	_ "embed"
	"log"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
	"github.com/mlorentedev/kubelab/apps/api/internal/store"
	"github.com/mlorentedev/kubelab/apps/api/pkg/config"
)

// The console has its own host, which Authelia guards whole (CONSOLE-004 AC3).
// The same binary answers the public API host, so /console is served only to a
// request for the console's host, and to none when no host is declared: through
// api.kubelab.live it is a 404, never the page.

//go:embed console.html
var consolePage []byte

// QueueReader is the console's view of the read model.
type QueueReader interface {
	Queue(ctx context.Context, sources []forge.Source) ([]forge.SourceState, []forge.Item, error)
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

// Deps returns the read model and the declared sources; a seam for tests.
type Deps func() (QueueReader, string, error)

// Live reads the running configuration.
func Live() (QueueReader, string, error) {
	conf, err := config.GetConfig()
	if err != nil {
		return nil, "", err
	}
	return store.ForgeModel{Conf: conf.Postgres}, conf.Forge.Sources, nil
}

// LiveDomain is the console's declared host, empty when none is.
func LiveDomain() string {
	conf, err := config.GetConfig()
	if err != nil {
		return ""
	}
	return conf.Forge.ConsoleDomain
}

// Register adds the console's routes, answered only for its own host.
func Register(r *gin.Engine, deps Deps, domain func() string) {
	g := r.Group("/console", onlyHost(domain))
	g.GET("", func(c *gin.Context) { c.Redirect(http.StatusMovedPermanently, "/console/") })
	g.GET("/", func(c *gin.Context) { c.Data(http.StatusOK, "text/html; charset=utf-8", consolePage) })
	g.GET("/queue", func(c *gin.Context) { queueHandler(c, deps) })
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
	reader, spec, err := deps()
	if err != nil {
		log.Printf("console queue: configuration unavailable")
		c.Status(http.StatusServiceUnavailable)
		return
	}
	sources, err := forge.ParseSources(spec)
	if err != nil {
		log.Printf("console queue: sources: %v", err)
		c.Status(http.StatusServiceUnavailable)
		return
	}
	out := struct {
		Sources []sourceView `json:"sources"`
		Items   []itemView   `json:"items"`
	}{Sources: []sourceView{}, Items: []itemView{}}
	if len(sources) > 0 {
		states, items, err := reader.Queue(c.Request.Context(), sources)
		if err != nil {
			log.Printf("console queue: %v", err)
			c.Status(http.StatusServiceUnavailable)
			return
		}
		for _, st := range states {
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
