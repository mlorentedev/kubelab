package forge_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

func newGitHubWriter(baseURL string) forge.Writer {
	return &forge.GitHubWriter{BaseURL: baseURL, Token: "t"}
}

func setGitHubWriterHTTP(w forge.Writer, c *http.Client) { w.(*forge.GitHubWriter).HTTP = c }

var ghSrc = forge.Source{Forge: "github", Owner: "o", Repo: "r"}

// GitHub REST, api.github.com 2022-11-28 (rest-api-description 1.1.4). Each row's comment says
// which operation it is and what the description says that row's answer is.
func TestGitHubWriter(t *testing.T) {
	const marker = "<!-- kubelab-write:42 -->"
	runWriterContract(t, writerContract{
		Forge: "github",
		Auth:  "Bearer t",
		Headers: map[string]string{
			"Accept":               "application/vnd.github+json",
			"X-GitHub-Api-Version": "2022-11-28",
		},
		New: newGitHubWriter,
		Cases: []writeCase{
			{
				// issues/create: 201 with the issue. The body ends with the hidden marker (W4).
				Name:  "create carries the marker and returns number and url",
				Write: forge.Write{Action: forge.ActionCreate, Source: ghSrc, OutboxID: 42, Title: "T", Body: "B"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues", Status: 201,
					Body:   map[string]any{"title": "T", "body": "B\n\n" + marker},
					Answer: `{"number":7,"html_url":"https://github.com/o/r/issues/7","body":"B"}`}},
				Want: wantResult{forge.OutcomeApplied, 201, 7, "https://github.com/o/r/issues/7"},
			},
			{
				Name:  "create with no body is the marker alone",
				Write: forge.Write{Action: forge.ActionCreate, Source: ghSrc, OutboxID: 9, Title: "T"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues", Status: 201,
					Body:   map[string]any{"title": "T", "body": "<!-- kubelab-write:9 -->"},
					Answer: `{"number":8,"html_url":"https://github.com/o/r/issues/8"}`}},
				Want: wantResult{forge.OutcomeApplied, 201, 8, "https://github.com/o/r/issues/8"},
			},
			{
				// A 2xx that names no issue cannot be returned to the caller, and the issue may exist:
				// UNKNOWN sends the worker to the marker search instead of a second create.
				Name:  "create answered 2xx with no number is unknown, never retried blind",
				Write: forge.Write{Action: forge.ActionCreate, Source: ghSrc, OutboxID: 42, Title: "T"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues", Status: 201,
					Body: map[string]any{"title": "T", "body": marker}, Answer: `<html>`}},
				Want: wantResult{forge.OutcomeUnknown, 201, 0, ""},
			},
			{
				// issues/add-labels: 200 with the issue's labels. A label already there is no error.
				// The label has a space and a slash, and goes in the JSON body, not in a path.
				Name:  "add_label applied, and a label already on the issue is applied too",
				Write: forge.Write{Action: forge.ActionAddLabel, Source: ghSrc, Number: 5, Label: "area: infra/dns"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues/5/labels", Status: 200,
					Body:   map[string]any{"labels": []any{"area: infra/dns"}},
					Answer: `[{"name":"bug"},{"name":"area: infra/dns"}]`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				Name:  "add_label whose answer lacks the label is a terminal failure, not a 2xx success",
				Write: forge.Write{Action: forge.ActionAddLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues/5/labels", Status: 200,
					Body: map[string]any{"labels": []any{"x"}}, Answer: `[{"name":"bug"}]`}},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 200},
			},
			{
				// issues/remove-label: 200 with the remaining labels. The name is one path segment.
				Name:  "remove_label escapes the name into one path segment",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "area: infra/dns"},
				Calls: []exchange{{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/area:%20infra%2Fdns", Status: 200, Answer: `[]`}},
				Want:  wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				// The description: 404 "if the label does not exist". That is also the answer for an
				// issue that is gone, so the 404 alone settles nothing: read the issue's labels. A retry
				// after a lost answer must not turn an applied removal into a terminal failure.
				Name:  "remove_label 404 then the issue's labels lack it: already removed, applied",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{
					{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/x", Status: 404, Answer: `{"message":"Label does not exist"}`},
					{Method: "GET", Path: "/repos/o/r/issues/5/labels", Query: "per_page=100", Status: 200, Answer: `[{"name":"bug"}]`},
				},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				// Only a 404 is ambiguous. Any other refusal is what it says, with no second call.
				Name:  "remove_label refused with 403 is terminal after one call",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/x", Status: 403, Answer: `{"message":"Forbidden"}`}},
				Want:  wantResult{Outcome: forge.OutcomeFailed, Status: 403},
			},
			{
				Name:  "remove_label answered 502 is retryable after one call",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/x", Status: 502, Answer: `{}`}},
				Want:  wantResult{Outcome: forge.OutcomeRetry, Status: 502},
			},
			{
				Name:  "remove_label 404 then the issue is gone: terminal failure",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{
					{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/x", Status: 404, Answer: `{"message":"Not Found"}`},
					{Method: "GET", Path: "/repos/o/r/issues/5/labels", Query: "per_page=100", Status: 404, Answer: `{"message":"Not Found"}`},
				},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 404},
			},
			{
				Name:  "remove_label 404 then the label is still there: the answers disagree, so retry",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{
					{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/x", Status: 404, Answer: `{}`},
					{Method: "GET", Path: "/repos/o/r/issues/5/labels", Query: "per_page=100", Status: 200, Answer: `[{"name":"x"}]`},
				},
				Want: wantResult{Outcome: forge.OutcomeRetry, Status: 404},
			},
			{
				Name:  "remove_label 404 then the probe is down: retry",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: ghSrc, Number: 5, Label: "x"},
				Calls: []exchange{
					{Method: "DELETE", Path: "/repos/o/r/issues/5/labels/x", Status: 404, Answer: `{}`},
					{Method: "GET", Path: "/repos/o/r/issues/5/labels", Query: "per_page=100", Status: 502, Answer: `{}`},
				},
				Want: wantResult{Outcome: forge.OutcomeRetry, Status: 502},
			},
			{
				// issues/add-assignees: 201 with the issue. Users who cannot be assigned are ignored,
				// so the answer is what says whether the assignee took.
				Name:  "add_assignee applied when the issue carries the login",
				Write: forge.Write{Action: forge.ActionAddAssignee, Source: ghSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues/5/assignees", Status: 201,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":[{"login":"Bob"}]}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 201},
			},
			{
				Name:  "add_assignee silently ignored by the forge is a terminal failure",
				Write: forge.Write{Action: forge.ActionAddAssignee, Source: ghSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "POST", Path: "/repos/o/r/issues/5/assignees", Status: 201,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":[]}`}},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 201},
			},
			{
				// issues/remove-assignees: 200 with the issue; DELETE with a JSON body.
				Name:  "remove_assignee sends its body on a DELETE",
				Write: forge.Write{Action: forge.ActionRemoveAssignee, Source: ghSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "DELETE", Path: "/repos/o/r/issues/5/assignees", Status: 200,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":[]}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				// issues/update: 200. Closing a closed issue is a 200 too, so it is applied.
				Name:  "close",
				Write: forge.Write{Action: forge.ActionClose, Source: ghSrc, Number: 5},
				Calls: []exchange{{Method: "PATCH", Path: "/repos/o/r/issues/5", Status: 200,
					Body: map[string]any{"state": "closed"}, Answer: `{"state":"closed"}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				Name:  "reopen",
				Write: forge.Write{Action: forge.ActionReopen, Source: ghSrc, Number: 5},
				Calls: []exchange{{Method: "PATCH", Path: "/repos/o/r/issues/5", Status: 200,
					Body: map[string]any{"state": "open"}, Answer: `{"state":"open"}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
		},
	})
}

func TestGitHubWriterStatusClasses(t *testing.T) { runStatusClasses(t, newGitHubWriter) }

func TestGitHubWriterWithNoAnswer(t *testing.T) {
	runNoAnswer(t, newGitHubWriter, setGitHubWriterHTTP)
}

func TestGitHubWriterRefusesWhatItCannotMake(t *testing.T) { runInvalidWrites(t, newGitHubWriter) }

// A token that does not mint sent nothing, so even a create is retryable and the forge is not called.
func TestGitHubWriterTokenFailureIsRetryableAndSendsNothing(t *testing.T) {
	var hits int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
	defer srv.Close()
	boom := errors.New("mint failed")
	w := &forge.GitHubWriter{BaseURL: srv.URL, Tokens: func(context.Context) (string, error) { return "", boom }}

	got := w.Write(context.Background(), forge.Write{Action: forge.ActionCreate, Source: ghSrc, OutboxID: 1, Title: "t"})
	if got.Outcome != forge.OutcomeRetry || !errors.Is(got.Err, boom) || hits != 0 {
		t.Fatalf("got %+v after %d call(s)", got, hits)
	}
}

// The App's installation token wins over a static one, and is asked for per write.
func TestGitHubWriterTakesAFreshTokenPerWrite(t *testing.T) {
	var auth []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = append(auth, r.Header.Get("Authorization"))
		_, _ = w.Write([]byte(`{"state":"closed"}`))
	}))
	defer srv.Close()
	n := 0
	w := &forge.GitHubWriter{BaseURL: srv.URL, Token: "static", Tokens: func(context.Context) (string, error) {
		n++
		return "app-" + string(rune('0'+n)), nil
	}}
	for i := 0; i < 2; i++ {
		if got := w.Write(context.Background(), forge.Write{Action: forge.ActionClose, Source: ghSrc, Number: 1}); got.Outcome != forge.OutcomeApplied {
			t.Fatalf("%+v", got)
		}
	}
	if len(auth) != 2 || auth[0] != "Bearer app-1" || auth[1] != "Bearer app-2" {
		t.Fatalf("authorization %v", auth)
	}
}

// With no credential at all the adapter is not configured: it never sends an anonymous write.
func TestGitHubWriterWithNoCredentialSendsNothing(t *testing.T) {
	var hits int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
	defer srv.Close()
	got := (&forge.GitHubWriter{BaseURL: srv.URL}).Write(context.Background(),
		forge.Write{Action: forge.ActionClose, Source: ghSrc, Number: 1})
	if got.Outcome != forge.OutcomeFailed || !errors.Is(got.Err, forge.ErrNoWriter) || hits != 0 {
		t.Fatalf("got %+v after %d call(s)", got, hits)
	}
}
