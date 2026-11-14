package api

import (
	"crypto/subtle"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// forgeCreate is the one write a machine may make (CONSOLE-004 AC3): create an issue, for
// n8n's Slack capture (CONSOLE-007). It sits on the api host with no session in front, like
// the webhook receiver, because Authelia's ForwardAuth does not forward Authorization: a
// Bearer sent to the console host never reaches the pod. It is the only handler that reads
// the token, so every other route refuses it by construction.
//
// An empty token, none declared, accepts nobody.
func forgeCreate(token string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !bearerMatches(c.GetHeader("Authorization"), token) {
			c.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		// The write itself lands with the outbox (AC2): the route and its guard exist first.
		c.Status(http.StatusNotImplemented)
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
