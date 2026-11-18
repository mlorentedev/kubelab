package api

import (
	"crypto/subtle"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/mlorentedev/kubelab/apps/api/internal/console"
)

// forgeCreate is the one write a machine may make (CONSOLE-004 AC3): create an issue, for
// n8n's Slack capture (CONSOLE-007). It sits on the api host with no session in front, like
// the webhook receiver, because Authelia's ForwardAuth does not forward Authorization: a
// Bearer sent to the console host never reaches the pod. It is the only handler that reads
// the token, so every other route refuses it by construction.
//
// It takes the same body as the console's create ({source, title, body}) and the same
// Idempotency-Key, goes through the same intake and answers the same receipts; the actor is
// forge.MachineActor. An empty token, none declared, accepts nobody.
func forgeCreate(token string, writes *console.Writes) gin.HandlerFunc {
	create := writes.Machine()
	return func(c *gin.Context) {
		if !bearerMatches(c.GetHeader("Authorization"), token) {
			c.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		create(c)
	}
}

func bearerMatches(header, token string) bool {
	if token == "" {
		return false
	}
	presented, ok := strings.CutPrefix(header, "Bearer ")
	if !ok {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(presented), []byte(token)) == 1
}
