package forge

import (
	"context"
	"errors"
	"testing"
)

type countingEnqueuer struct{ n int }

func (c *countingEnqueuer) Enqueue(context.Context, Enqueue) (Receipt, error) {
	c.n++
	return Receipt{ID: 1, Status: "pending"}, nil
}

type noKinds struct{}

func (noKinds) ItemKind(context.Context, Source, int) (Kind, bool, error) { return "", false, nil }

type silentWriter struct{ Writer }

func newIntake(store *countingEnqueuer) *Intake {
	src := Source{Forge: "gitea", Owner: "personal", Repo: "sandbox"}
	return &Intake{
		Store: store, Kinds: noKinds{},
		Writers: map[string]Writer{"gitea": silentWriter{}},
		Sources: func() ([]Source, error) { return []Source{src}, nil },
	}
}

// An actor is what a replay is keyed on (UNIQUE (actor, idempotency_key)): a request with none
// would share a namespace with every other request that has none, so it is refused, and nothing
// is enqueued.
func TestAnIntakeRefusesARequestWithNoActor(t *testing.T) {
	for _, actor := range []string{"", "   ", "\t"} {
		store := &countingEnqueuer{}
		_, err := newIntake(store).Accept(context.Background(), Request{
			Actor: actor, Key: "k1", Action: ActionClose,
			Source: Source{Forge: "gitea", Owner: "personal", Repo: "sandbox"}, Number: 3,
		})
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("actor %q: want ErrInvalid, got %v", actor, err)
		}
		if store.n != 0 {
			t.Fatalf("actor %q: a refused request was enqueued", actor)
		}
	}
}
