package services

// Echo integration: dynamic multi-branch wiki.
// - Discovers branches via GitHub API (ETag).
// - Per-branch tarball sync to /data/content/<branch> (ETag).
// - Renders README.md (/) and /docs/** (server-side).
// - Per-branch in-memory search.
// - Branch selection via ?branch=... and cookie.

import (
	"context"
	"html/template"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/labstack/echo/v4"

	"your/module/path/src/internal/wiki/gh"
	"your/module/path/src/internal/wiki/render"
	"your/module/path/src/internal/wiki/search"
	syncsrc "your/module/path/src/internal/wiki/sync"
)

type Config struct {
	Owner, Repo, Token string
	ContentRoot        string // e.g., "/data/content"
	Allow, Deny        []string
	PollMinutes        int
	TemplatesGlob      string // e.g., "templates/wiki/*.html"
	StaticPrefix       string // e.g., "/static" (optional if you decide to serve assets)
}

type PageData struct {
	Title         string
	HTML          template.HTML
	Branches      []string
	CurrentBranch string
}

type BranchState struct {
	Name       string
	ContentDir string
	idx        *search.Index
	mu         sync.RWMutex
}

func (bs *BranchState) SetIndex(i *search.Index) { bs.mu.Lock(); bs.idx = i; bs.mu.Unlock() }
func (bs *BranchState) GetIndex() *search.Index  { bs.mu.RLock(); defer bs.mu.RUnlock(); return bs.idx }

type Registry struct {
	mu       sync.RWMutex
	branches []string
	states   map[string]*BranchState
}

func newRegistry() *Registry { return &Registry{states: map[string]*BranchState{}} }
func (r *Registry) GetBranches() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return append([]string{}, r.branches...)
}
func (r *Registry) Has(name string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, ok := r.states[name]
	return ok
}
func (r *Registry) Get(name string) *BranchState {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.states[name]
}
func (r *Registry) upsert(name string, bs *BranchState) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.states[name]; !ok {
		r.states[name] = bs
	}
	list := make([]string, 0, len(r.states))
	for n := range r.states {
		list = append(list, n)
	}
	r.branches = list
}

func matchAny(patterns []string, s string) bool {
	for _, p := range patterns {
		if ok, _ := path.Match(p, s); ok {
			return true
		}
	}
	return false
}

func resolveBranch(c echo.Context, options []string) string {
	// 1) query ?branch=
	q := strings.TrimSpace(c.QueryParam("branch"))
	// 2) cookie
	if q == "" {
		if ck, err := c.Cookie("branch"); err == nil {
			q = ck.Value
		}
	}
	// validate
	for _, b := range options {
		if b == q {
			http.SetCookie(c.Response(), &http.Cookie{
				Name: "branch", Value: b, Path: "/",
				HttpOnly: false, SameSite: http.SameSiteLaxMode,
				MaxAge: 60 * 60 * 24 * 30,
			})
			return b
		}
	}
	// default: first
	if len(options) > 0 {
		def := options[0]
		http.SetCookie(c.Response(), &http.Cookie{
			Name: "branch", Value: def, Path: "/",
			HttpOnly: false, SameSite: http.SameSiteLaxMode,
			MaxAge: 60 * 60 * 24 * 30,
		})
		return def
	}
	return ""
}

func renderMD(c echo.Context, tmpl *template.Template, mdPath string, branches []string, current string) error {
	b, err := os.ReadFile(mdPath)
	if err != nil {
		return c.String(http.StatusNotFound, "Not found")
	}
	html, err := render.MarkdownToHTML(b)
	if err != nil {
		return c.String(http.StatusInternalServerError, "Render error")
	}
	data := PageData{
		Title:         titleFromMD(b),
		HTML:          template.HTML(html),
		Branches:      branches,
		CurrentBranch: current,
	}
	return tmpl.ExecuteTemplate(c.Response(), "page.html", data)
}

func titleFromMD(b []byte) string {
	for _, ln := range strings.Split(string(b), "\n") {
		ln = strings.TrimSpace(ln)
		if strings.HasPrefix(ln, "# ") {
			return strings.TrimPrefix(ln, "# ")
		}
	}
	return "Untitled"
}

// Register mounts the wiki routes into the provided Echo instance.
func Register(e *echo.Echo, cfg Config) error {
	reg := newRegistry()

	// Templates (kept simple; you can integrate your renderer if you have one)
	tmpl := template.Must(template.ParseGlob(cfg.TemplatesGlob))

	// Dynamic branch discovery
	poll := time.Duration(cfg.PollMinutes) * time.Minute
	fetcher := gh.NewBranchFetcher(cfg.Owner, cfg.Repo, cfg.Token, poll)

	go fetcher.Start(context.Background(), func(names []string) {
		// filter allow/deny
		var keep []string
		for _, n := range names {
			if len(cfg.Allow) > 0 && !matchAny(cfg.Allow, n) {
				continue
			}
			if len(cfg.Deny) > 0 && matchAny(cfg.Deny, n) {
				continue
			}
			keep = append(keep, n)
		}
		// ensure state & updater per branch
		for _, br := range keep {
			if reg.Has(br) {
				continue
			}
			dir := filepath.Join(cfg.ContentRoot, br)
			_ = os.MkdirAll(dir, 0o755)
			bs := &BranchState{Name: br, ContentDir: dir}
			// initial index (may be empty)
			i, _ := search.NewIndex(filepath.Join(dir, "docs"), filepath.Join(dir, "README.md"))
			bs.SetIndex(i)
			reg.upsert(br, bs)

			// start tarball updater
			up := syncsrc.NewUpdater(syncsrc.Config{
				Owner: cfg.Owner, Repo: cfg.Repo, Branch: br, Token: cfg.Token,
				PollInterval: poll, DataDir: dir,
			})
			go up.Start(context.Background(), func(active string) error {
				n, err := search.NewIndex(filepath.Join(active, "docs"), filepath.Join(active, "README.md"))
				if err == nil {
					bs.SetIndex(n)
				}
				return nil
			})
		}
	})

	// --- Routes ---

	// Search (fragment)
	e.GET("/search", func(c echo.Context) error {
		branches := reg.GetBranches()
		br := resolveBranch(c, branches)
		bs := reg.Get(br)
		if bs == nil {
			return c.String(http.StatusServiceUnavailable, "Branch not ready")
		}
		q := c.QueryParam("q")
		results := bs.GetIndex().Query(q)
		return tmpl.ExecuteTemplate(c.Response(), "search_results.html", results)
	})

	// Home "/"
	e.GET("/", func(c echo.Context) error {
		branches := reg.GetBranches()
		br := resolveBranch(c, branches)
		bs := reg.Get(br)
		if bs == nil {
			return c.String(http.StatusServiceUnavailable, "Branch not ready")
		}
		return renderMD(c, tmpl, filepath.Join(bs.ContentDir, "README.md"), branches, br)
	})

	// Any path -> /docs/<path>.md or /docs/<path>/index.md
	e.GET("/*", func(c echo.Context) error {
		branches := reg.GetBranches()
		br := resolveBranch(c, branches)
		bs := reg.Get(br)
		if bs == nil {
			return c.String(http.StatusServiceUnavailable, "Branch not ready")
		}
		p := c.Param("*")
		if p == "" || p == "/" {
			return renderMD(c, tmpl, filepath.Join(bs.ContentDir, "README.md"), branches, br)
		}
		md := filepath.Join(bs.ContentDir, "docs", strings.TrimPrefix(p, "/")+".md")
		if _, err := os.Stat(md); os.IsNotExist(err) {
			md = filepath.Join(bs.ContentDir, "docs", strings.TrimPrefix(p, "/"), "index.md")
		}
		if _, err := os.Stat(md); err != nil {
			return c.String(http.StatusNotFound, "Not found")
		}
		return renderMD(c, tmpl, md, branches, br)
	})

	return nil
}
