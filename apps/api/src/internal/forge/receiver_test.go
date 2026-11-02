package forge_test

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

type fakeStore struct {
	events []forge.Event
	err    error
}

func (f *fakeStore) StoreEvent(_ context.Context, e forge.Event) error {
	if f.err != nil {
		return f.err
	}
	f.events = append(f.events, e)
	return nil
}

func header(pairs ...string) http.Header {
	h := http.Header{}
	for i := 0; i < len(pairs); i += 2 {
		h.Set(pairs[i], pairs[i+1])
	}
	return h
}

func TestReceiver(t *testing.T) {
	const secret, body = "fixture", `{"action":"opened"}`
	sig := sign(secret, body)
	github := func(s string) http.Header {
		return header("X-Hub-Signature-256", s, "X-GitHub-Delivery", "d1", "X-GitHub-Event", "issues")
	}
	gitea := header("X-Gitea-Signature", sig, "X-Gitea-Delivery", "d2", "X-Gitea-Event", "issues")

	cases := []struct {
		name    string
		forge   string
		header  http.Header
		body    string
		secrets map[string]string
		err     error
		want    int
		stored  int
	}{
		{name: "github", forge: "github", header: github("sha256=" + sig), body: body, want: 202, stored: 1},
		{name: "gitea", forge: "gitea", header: gitea, body: body, want: 202, stored: 1},
		{name: "bad signature stores nothing", forge: "github", header: github("sha256=00"), body: body, want: 401},
		{name: "another forge's secret", forge: "gitea", header: gitea, body: body, want: 401,
			secrets: map[string]string{"github": secret}},
		{name: "no secret rejects", forge: "gitea", header: gitea, body: body, want: 401, secrets: map[string]string{}},
		{name: "unknown forge", forge: "gitlab", header: gitea, body: body, want: 404},
		{name: "no delivery id", forge: "gitea", body: body, want: 400,
			header: header("X-Gitea-Signature", sig, "X-Gitea-Event", "issues")},
		{name: "store down asks for redelivery", forge: "gitea", header: gitea, body: body, want: 503,
			err: errors.New("down")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			secrets := c.secrets
			if secrets == nil {
				secrets = map[string]string{"github": secret, "gitea": secret}
			}
			st := &fakeStore{err: c.err}
			rc := &forge.Receiver{Secrets: secrets, Store: st}
			if got := rc.Handle(context.Background(), c.forge, c.header, strings.NewReader(c.body)); got != c.want {
				t.Fatalf("status = %d, want %d", got, c.want)
			}
			if len(st.events) != c.stored {
				t.Fatalf("stored %d, want %d", len(st.events), c.stored)
			}
			for _, e := range st.events {
				if e.Forge != c.forge || e.DeliveryID == "" || e.Type != "issues" || string(e.Payload) != c.body {
					t.Fatalf("stored %+v", e)
				}
			}
		})
	}
}

func TestReceiverRejectsSignedGarbage(t *testing.T) {
	const secret, body = "fixture", "not json"
	rc := &forge.Receiver{Secrets: map[string]string{"gitea": secret}, Store: &fakeStore{}}
	h := header("X-Gitea-Signature", sign(secret, body), "X-Gitea-Delivery", "d", "X-Gitea-Event", "issues")
	if got := rc.Handle(context.Background(), "gitea", h, strings.NewReader(body)); got != 400 {
		t.Fatalf("status = %d, want 400", got)
	}
}
