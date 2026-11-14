package console

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

// apps/console develops against recorded answers of GET /console/queue (ADR-074 Consequences:
// the dev loop needs a path with no session). A recording that no longer matches what this
// handler writes would leave the frontend green against a shape the API stopped sending, so
// every fixture is held to queueView here: no key it does not know, none of its keys missing,
// and values the handler could have produced.
const fixturesGlob = "../../../../console/fixtures/*/page-*.json"

func jsonKeys(t *testing.T, raw []byte) []string {
	t.Helper()
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// emittedKeys are the keys the handler writes for v, read from its own marshalling.
func emittedKeys(t *testing.T, v any) []string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return jsonKeys(t, b)
}

func TestFixturesMatchTheQueueContract(t *testing.T) {
	files, err := filepath.Glob(fixturesGlob)
	if err != nil || len(files) == 0 {
		t.Fatalf("no console fixtures at %s (err %v): the frontend's dev loop reads them", fixturesGlob, err)
	}
	for _, file := range files {
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.DisallowUnknownFields()
		var got queueView
		if err := dec.Decode(&got); err != nil {
			t.Fatalf("%s no longer decodes as the handler's answer: %v", file, err)
		}

		if want := emittedKeys(t, queueView{}); !reflect.DeepEqual(jsonKeys(t, raw), want) {
			t.Fatalf("%s top-level keys %v, handler writes %v", file, jsonKeys(t, raw), want)
		}
		var parts struct {
			Sources []json.RawMessage `json:"sources"`
			Items   []json.RawMessage `json:"items"`
		}
		if err := json.Unmarshal(raw, &parts); err != nil {
			t.Fatal(err)
		}
		for _, s := range parts.Sources {
			if want := emittedKeys(t, sourceView{}); !reflect.DeepEqual(jsonKeys(t, s), want) {
				t.Fatalf("%s source keys %v, handler writes %v", file, jsonKeys(t, s), want)
			}
		}
		for _, it := range parts.Items {
			if want := emittedKeys(t, itemView{}); !reflect.DeepEqual(jsonKeys(t, it), want) {
				t.Fatalf("%s item keys %v, handler writes %v", file, jsonKeys(t, it), want)
			}
		}

		for _, s := range got.Sources {
			if src, err := forge.ParseSources(s.Source); err != nil || len(src) != 1 {
				t.Fatalf("%s source %q is not one the handler names", file, s.Source)
			}
		}
		for _, it := range got.Items {
			if src, err := forge.ParseSources(it.Source); err != nil || len(src) != 1 {
				t.Fatalf("%s item source %q is not one the handler names", file, it.Source)
			}
			if k := forge.Kind(it.Kind); k != forge.KindIssue && k != forge.KindPull {
				t.Fatalf("%s item kind %q is neither issue nor pull", file, it.Kind)
			}
		}
		// A cursor the fixtures hand out must be one the handler would accept back.
		if got.Next != nil {
			if _, err := decodeCursor(*got.Next); err != nil {
				t.Fatalf("%s next cursor is not one the handler issues: %v", file, err)
			}
		}
		if got.Total < len(got.Items) {
			t.Fatalf("%s total %d is below the page's %d items", file, got.Total, len(got.Items))
		}
	}
}
