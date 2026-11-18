package console

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// The narrow writes (ADR-066 A2, CONSOLE-004 AC2): create an issue, add or remove a
// label, assign or unassign, close or reopen. Nothing else: no merge, no review, no
// reviewer request, no content edit. `tests` in the api package hold the full engine to
// that, read from its routes rather than from this file.
//
// Every write is the signed-in operator's, named by the Remote-User header Authelia sets.
// The machine create that n8n calls (CONSOLE-007) is not registered here: Authelia's ForwardAuth
// does not forward Authorization, so it lives on the api host (`POST /api/forge/issues`) and
// calls Writes.Machine, so both doors judge a write by the same intake.
//
// A route does not call a forge. It judges the request (forge.Intake), keeps it in the outbox and
// answers 202; the worker sends it, and the queue's `writes` shows it until the forge confirms.
//
// Answers, for a write on any route:
//
//	202  accepted, pending; the body is the receipt
//	200  a replay of a request already settled (applied or failed); the body is the settled receipt
//	400  no or unusable Idempotency-Key, or a request that is malformed
//	401  no Authelia identity (the console routes) or no matching bearer (the machine route)
//	403  a Remote-User that names the machine actor
//	422  the key was used with a different request (action, target or body), or a request the
//	     platform does not perform: a target outside infra.forge.sources, a label outside
//	     status:* and priority:*, a pull request closed or reopened, text carrying the write marker
//	503  the environment takes no writes (the gate is off or the forge has no writer), or the
//	     declaration or the database cannot be read

// identityKey is where requireIdentity leaves the operator for the write handlers.
const identityKey = "console.identity"

// requireIdentity answers 401 to a write that does not name an Authelia identity. A browser
// never meets it: Authelia answers first. It guards a request that reached the pod without
// passing Authelia, since the host check alone can be satisfied from inside the cluster.
// It answers 403 to an identity that is the machine actor's name: an actor is half of an
// idempotency key's scope, and the machine's must not be claimable from a header.
func requireIdentity(c *gin.Context) {
	identity := strings.TrimSpace(c.GetHeader("Remote-User"))
	if identity == "" {
		c.AbortWithStatus(http.StatusUnauthorized)
		return
	}
	if strings.EqualFold(identity, forge.MachineActor) {
		c.AbortWithStatus(http.StatusForbidden)
		return
	}
	c.Set(identityKey, identity)
	c.Next()
}

// maxBody bounds a write's JSON body; the largest field is an issue body of 60 000 bytes.
const maxBody = 128 << 10

// Writes is what the write routes and the queue's `writes` need: the intake and the reader.
type Writes struct {
	Intake *forge.Intake
	Reader forge.WriteReader
	// Now is the clock the failed-write window is read against; time.Now when nil.
	Now func() time.Time
}

func (w *Writes) now() time.Time {
	if w != nil && w.Now != nil {
		return w.Now()
	}
	return time.Now()
}

// createBody is the body of both creates.
type createBody struct {
	Source string `json:"source"`
	Title  string `json:"title"`
	Body   string `json:"body"`
}

type labelBody struct {
	Label string `json:"label"`
}

type assigneeBody struct {
	Login string `json:"login"`
}

// writeResponse is the receipt every write route answers. Response is what the forge answered to
// an applied write (a created issue's number and url), null until then. Error is the last
// failure, null when there is none.
type writeResponse struct {
	ID       int64           `json:"id"`
	Status   string          `json:"status"`
	Response json.RawMessage `json:"response"`
	Error    *string         `json:"error"`
}

// registerWrites adds the write routes under the console's host-checked group.
func registerWrites(g *gin.RouterGroup, w *Writes) {
	r := g.Group("/issues", requireIdentity)
	r.POST("", w.create(func(c *gin.Context) string { return c.GetString(identityKey) }))
	item := r.Group("/:forge/:owner/:repo/:number")
	item.POST("/labels", w.onItem(forge.ActionAddLabel, labelBody{}))
	item.DELETE("/labels/:label", w.onItem(forge.ActionRemoveLabel, nil))
	item.POST("/assignees", w.onItem(forge.ActionAddAssignee, assigneeBody{}))
	item.DELETE("/assignees/:login", w.onItem(forge.ActionRemoveAssignee, nil))
	item.POST("/close", w.onItem(forge.ActionClose, nil))
	item.POST("/reopen", w.onItem(forge.ActionReopen, nil))
}

// Machine is the handler of the machine create: the caller has already checked the bearer. The
// actor is forge.MachineActor, whatever the request says.
func (w *Writes) Machine() gin.HandlerFunc {
	return w.create(func(*gin.Context) string { return forge.MachineActor })
}

func (w *Writes) create(actor func(*gin.Context) string) gin.HandlerFunc {
	return func(c *gin.Context) {
		var body createBody
		if !readJSON(c, &body) {
			return
		}
		src, err := parseSource(body.Source)
		if err != nil {
			respond(c, forge.Receipt{}, err)
			return
		}
		w.accept(c, forge.Request{Actor: actor(c), Action: forge.ActionCreate, Source: src, Title: body.Title, Body: body.Body})
	}
}

// onItem builds the handler of a write on an issue named in the path. bodyShape is a zero value
// of the JSON body the action reads, nil when it takes none.
func (w *Writes) onItem(action forge.Action, bodyShape any) gin.HandlerFunc {
	return func(c *gin.Context) {
		number, err := strconv.Atoi(c.Param("number"))
		if err != nil {
			respond(c, forge.Receipt{}, invalid("the issue number must be a positive integer"))
			return
		}
		req := forge.Request{
			Actor: c.GetString(identityKey), Action: action, Number: number,
			Source: forge.Source{Forge: c.Param("forge"), Owner: c.Param("owner"), Repo: c.Param("repo")},
			Label:  c.Param("label"), Login: c.Param("login"),
		}
		switch bodyShape.(type) {
		case labelBody:
			var b labelBody
			if !readJSON(c, &b) {
				return
			}
			req.Label = b.Label
		case assigneeBody:
			var b assigneeBody
			if !readJSON(c, &b) {
				return
			}
			req.Login = b.Login
		}
		w.accept(c, req)
	}
}

func (w *Writes) accept(c *gin.Context, req forge.Request) {
	req.Key = strings.TrimSpace(c.GetHeader("Idempotency-Key"))
	var intake *forge.Intake
	if w != nil {
		intake = w.Intake
	}
	receipt, err := intake.Accept(c.Request.Context(), req)
	respond(c, receipt, err)
}

// parseSource reads `<forge>:<owner>/<repo>`, the form GET /console/queue names a source in.
func parseSource(raw string) (forge.Source, error) {
	src, err := forge.ParseSources(raw)
	if err != nil || len(src) != 1 {
		return forge.Source{}, invalid("the source must be <forge>:<owner>/<repo>")
	}
	return src[0], nil
}

func invalid(msg string) error { return fmt.Errorf("%w: %s", forge.ErrInvalid, msg) }

// readJSON decodes the request body into v, refusing unknown fields, a second value and a body
// over maxBody. It answers 400 itself and reports false on failure.
func readJSON(c *gin.Context, v any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(c.Writer, c.Request.Body, maxBody))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		respond(c, forge.Receipt{}, invalid("the body must be one JSON object of the documented fields"))
		return false
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		respond(c, forge.Receipt{}, invalid("the body must be one JSON object"))
		return false
	}
	return true
}

// respond answers a write: the receipt on success, the class of the refusal otherwise. A failure
// of the platform's own (the database) is logged and answered without its text.
func respond(c *gin.Context, r forge.Receipt, err error) {
	switch {
	case err == nil:
		out := writeResponse{ID: r.ID, Status: r.State(), Response: r.Response}
		if r.LastError != "" {
			out.Error = &r.LastError
		}
		code := http.StatusAccepted
		if r.Replay && out.Status != forge.StatusPending {
			code = http.StatusOK
		}
		c.JSON(code, out)
	case errors.Is(err, forge.ErrInvalid):
		c.JSON(http.StatusBadRequest, gin.H{"error": refusalText(err, forge.ErrInvalid)})
	case errors.Is(err, forge.ErrKeyReuse):
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": forge.ErrKeyReuse.Error()})
	case errors.Is(err, forge.ErrRefused):
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": refusalText(err, forge.ErrRefused)})
	case errors.Is(err, forge.ErrUnavailable):
		log.Printf("console write: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "writes are not available"})
	default:
		log.Printf("console write: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "writes are not available"})
	}
}

// refusalText is the reason a client is told, without the class's own name in front of it.
func refusalText(err, class error) string {
	return strings.TrimPrefix(err.Error(), class.Error()+": ")
}

// writeView is one entry of the queue's `writes`: a write still owed, or one that failed in the
// last forge.FailedShownFor. Number is null for a create the forge has not answered. Detail is a
// create's title, or the label or login of the others, never an issue body.
type writeView struct {
	ID       int64     `json:"id"`
	Action   string    `json:"action"`
	Source   string    `json:"source"`
	Number   *int      `json:"number"`
	Detail   string    `json:"detail"`
	Status   string    `json:"status"`
	Error    *string   `json:"error"`
	QueuedAt time.Time `json:"queued_at"`
}

// writes reads the outbox for the queue. With no reader nothing is owed and nothing is shown.
func (w *Writes) writes(ctx context.Context) ([]writeView, error) {
	out := []writeView{}
	if w == nil || w.Reader == nil {
		return out, nil
	}
	rows, err := w.Reader.Writes(ctx, w.now().Add(-forge.FailedShownFor))
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		v := writeView{ID: r.ID, Action: string(r.Action), Source: r.Source.String(), Detail: r.Detail, Status: r.Status, QueuedAt: r.QueuedAt}
		if r.Number > 0 {
			n := r.Number
			v.Number = &n
		}
		if r.LastError != "" {
			e := r.LastError
			v.Error = &e
		}
		out = append(out, v)
	}
	return out, nil
}
