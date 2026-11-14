package console

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// The narrow writes (ADR-066 A2, CONSOLE-004 AC2): create an issue, add or remove a
// label, assign or unassign, close or reopen. Nothing else: no merge, no review, no
// reviewer request, no content edit. `tests` in the api package hold the full engine to
// that, read from its routes rather than from this file.
//
// Every write is the signed-in operator's, named by the Remote-User header Authelia sets.
// The machine create that n8n calls (CONSOLE-007) is not here: Authelia's ForwardAuth does
// not forward Authorization, so it lives on the api host (`POST /api/forge/issues`).

// identityKey is where requireIdentity leaves the operator for the write handlers.
const identityKey = "console.identity"

// requireIdentity answers 401 to a write that does not name an Authelia identity. A browser
// never meets it: Authelia answers first. It guards a request that reached the pod without
// passing Authelia, since the host check alone can be satisfied from inside the cluster.
func requireIdentity(c *gin.Context) {
	identity := strings.TrimSpace(c.GetHeader("Remote-User"))
	if identity == "" {
		c.AbortWithStatus(http.StatusUnauthorized)
		return
	}
	c.Set(identityKey, identity)
	c.Next()
}

// registerWrites adds the write routes under the console's host-checked group.
func registerWrites(g *gin.RouterGroup) {
	w := g.Group("/issues", requireIdentity)
	w.POST("", notYet)
	item := w.Group("/:forge/:owner/:repo/:number")
	item.POST("/labels", notYet)
	item.DELETE("/labels/:label", notYet)
	item.POST("/assignees", notYet)
	item.DELETE("/assignees/:login", notYet)
	item.POST("/close", notYet)
	item.POST("/reopen", notYet)
}

// notYet answers every write until the outbox lands: the route and its guard exist, the
// write does not.
func notYet(c *gin.Context) { c.Status(http.StatusNotImplemented) }
