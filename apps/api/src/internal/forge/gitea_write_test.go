package forge_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/mlorentedev/kubelab/apps/api/internal/forge"
)

func newGiteaWriter(baseURL string) forge.Writer {
	return &forge.GiteaWriter{BaseURL: baseURL, Token: "w"}
}

func setGiteaWriterHTTP(w forge.Writer, c *http.Client) { w.(*forge.GiteaWriter).HTTP = c }

var gtSrc = forge.Source{Forge: "gitea", Owner: "o", Repo: "r"}

// Gitea v1.27.3, read at the tag: routers/api/v1/api.go (the routes), repo/issue.go
// (CreateIssue answers 201, EditIssue answers 201 and does nothing for a state the issue
// already has), repo/issue_label.go (AddIssueLabels answers 200 with the issue's labels and
// ignores a name no label has; DeleteIssueLabel takes the label's numeric id and answers 204),
// repo/issue_assignee.go (AddIssueAssignees 201 and DeleteIssueAssignees 200, both with the issue).
func TestGiteaWriter(t *testing.T) {
	const marker = "<!-- kubelab-write:42 -->"
	runWriterContract(t, writerContract{
		Forge: "gitea",
		Auth:  "token w",
		New:   newGiteaWriter,
		Cases: []writeCase{
			{
				Name:  "create carries the marker and returns number and url",
				Write: forge.Write{Action: forge.ActionCreate, Source: gtSrc, OutboxID: 42, Title: "T", Body: "B"},
				Calls: []exchange{{Method: "POST", Path: "/api/v1/repos/o/r/issues", Status: 201,
					Body:   map[string]any{"title": "T", "body": "B\n\n" + marker},
					Answer: `{"number":724,"html_url":"https://git.example/o/r/issues/724"}`}},
				Want: wantResult{forge.OutcomeApplied, 201, 724, "https://git.example/o/r/issues/724"},
			},
			{
				Name:  "create answered 2xx with no number is unknown",
				Write: forge.Write{Action: forge.ActionCreate, Source: gtSrc, OutboxID: 42, Title: "T"},
				Calls: []exchange{{Method: "POST", Path: "/api/v1/repos/o/r/issues", Status: 201,
					Body: map[string]any{"title": "T", "body": marker}, Answer: `{"number":0}`}},
				Want: wantResult{forge.OutcomeUnknown, 201, 0, ""},
			},
			{
				// The names go in the body: IssueLabelsOption takes names or ids, and names need no lookup.
				Name:  "add_label applied when the answer lists the label",
				Write: forge.Write{Action: forge.ActionAddLabel, Source: gtSrc, Number: 5, Label: "area: infra/dns"},
				Calls: []exchange{{Method: "POST", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 200,
					Body:   map[string]any{"labels": []any{"area: infra/dns"}},
					Answer: `[{"id":3,"name":"bug"},{"id":11,"name":"area: infra/dns"}]`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				// prepareForReplaceOrAdd has no not-found branch for a name: an unknown label is dropped
				// and the handler still answers 200. The list in the answer is the only proof.
				Name:  "add_label of an unknown name answers 200 and is a terminal failure",
				Write: forge.Write{Action: forge.ActionAddLabel, Source: gtSrc, Number: 5, Label: "nope"},
				Calls: []exchange{{Method: "POST", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 200,
					Body: map[string]any{"labels": []any{"nope"}}, Answer: `[{"id":3,"name":"bug"}]`}},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 200},
			},
			{
				// DELETE takes the label id, so the issue's own labels are read to turn the name into one.
				Name:  "remove_label reads the issue's labels, then deletes by id",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: gtSrc, Number: 5, Label: "area: infra/dns"},
				Calls: []exchange{
					{Method: "GET", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 200,
						Answer: `[{"id":3,"name":"bug"},{"id":11,"name":"area: infra/dns"}]`},
					{Method: "DELETE", Path: "/api/v1/repos/o/r/issues/5/labels/11", Status: 204},
				},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 204},
			},
			{
				Name:  "remove_label of a label the issue does not carry is already applied, with no delete",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: gtSrc, Number: 5, Label: "x"},
				Calls: []exchange{{Method: "GET", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 200, Answer: `[{"id":3,"name":"bug"}]`}},
				Want:  wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				Name:  "remove_label on an issue that is gone is a terminal failure",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: gtSrc, Number: 5, Label: "x"},
				Calls: []exchange{{Method: "GET", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 404, Answer: `{}`}},
				Want:  wantResult{Outcome: forge.OutcomeFailed, Status: 404},
			},
			{
				Name:  "remove_label whose read is down is retryable",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: gtSrc, Number: 5, Label: "x"},
				Calls: []exchange{{Method: "GET", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 503, Answer: `{}`}},
				Want:  wantResult{Outcome: forge.OutcomeRetry, Status: 503},
			},
			{
				Name:  "remove_label whose delete is refused is a terminal failure",
				Write: forge.Write{Action: forge.ActionRemoveLabel, Source: gtSrc, Number: 5, Label: "x"},
				Calls: []exchange{
					{Method: "GET", Path: "/api/v1/repos/o/r/issues/5/labels", Status: 200, Answer: `[{"id":4,"name":"x"}]`},
					{Method: "DELETE", Path: "/api/v1/repos/o/r/issues/5/labels/4", Status: 403, Answer: `{}`},
				},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 403},
			},
			{
				Name:  "add_assignee applied when the issue carries the login",
				Write: forge.Write{Action: forge.ActionAddAssignee, Source: gtSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "POST", Path: "/api/v1/repos/o/r/issues/5/assignees", Status: 201,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":[{"login":"bob"}]}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 201},
			},
			{
				Name:  "add_assignee the issue does not carry afterwards is a terminal failure",
				Write: forge.Write{Action: forge.ActionAddAssignee, Source: gtSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "POST", Path: "/api/v1/repos/o/r/issues/5/assignees", Status: 201,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":null}`}},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 201},
			},
			{
				Name:  "remove_assignee sends its body on a DELETE",
				Write: forge.Write{Action: forge.ActionRemoveAssignee, Source: gtSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "DELETE", Path: "/api/v1/repos/o/r/issues/5/assignees", Status: 200,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":null}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 200},
			},
			{
				Name:  "remove_assignee whose answer still lists the login is a terminal failure",
				Write: forge.Write{Action: forge.ActionRemoveAssignee, Source: gtSrc, Number: 5, Login: "bob"},
				Calls: []exchange{{Method: "DELETE", Path: "/api/v1/repos/o/r/issues/5/assignees", Status: 200,
					Body: map[string]any{"assignees": []any{"bob"}}, Answer: `{"assignees":[{"login":"bob"}]}`}},
				Want: wantResult{Outcome: forge.OutcomeFailed, Status: 200},
			},
			{
				// closeOrReopenIssue does nothing for a state the issue already has, and EditIssue answers 201.
				Name:  "close",
				Write: forge.Write{Action: forge.ActionClose, Source: gtSrc, Number: 5},
				Calls: []exchange{{Method: "PATCH", Path: "/api/v1/repos/o/r/issues/5", Status: 201,
					Body: map[string]any{"state": "closed"}, Answer: `{"state":"closed"}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 201},
			},
			{
				Name:  "reopen",
				Write: forge.Write{Action: forge.ActionReopen, Source: gtSrc, Number: 5},
				Calls: []exchange{{Method: "PATCH", Path: "/api/v1/repos/o/r/issues/5", Status: 201,
					Body: map[string]any{"state": "open"}, Answer: `{"state":"open"}`}},
				Want: wantResult{Outcome: forge.OutcomeApplied, Status: 201},
			},
		},
	})
}

func TestGiteaWriterStatusClasses(t *testing.T) { runStatusClasses(t, newGiteaWriter) }

func TestGiteaWriterTruncatedAnswers(t *testing.T) { runTruncatedAnswers(t, newGiteaWriter) }

func TestGiteaWriterWithNoAnswer(t *testing.T) { runNoAnswer(t, newGiteaWriter, setGiteaWriterHTTP) }

func TestGiteaWriterRefusesWhatItCannotMake(t *testing.T) { runInvalidWrites(t, newGiteaWriter) }

// Unlike the reader, an empty token never means "send without Authorization": a write with
// no credential is not made at all, and the cause names the missing writer (W7: staging has none).
func TestGiteaWriterWithNoTokenSendsNothing(t *testing.T) {
	var hits int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
	defer srv.Close()
	got := (&forge.GiteaWriter{BaseURL: srv.URL}).Write(context.Background(),
		forge.Write{Action: forge.ActionClose, Source: gtSrc, Number: 1})
	if got.Outcome != forge.OutcomeFailed || !errors.Is(got.Err, forge.ErrNoWriter) || hits != 0 {
		t.Fatalf("got %+v after %d call(s)", got, hits)
	}
}
