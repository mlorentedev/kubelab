package forge

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// issueWriter is what the two forges' writers share: GitHub's and Gitea's issue endpoints take
// the same requests for a create, labels by name, assignees and a state change, and answer in the
// same JSON shapes. They differ in the root, the credential, how a label is removed and what a
// listing asks for, which are the hooks below.
type issueWriter struct {
	http *http.Client
	// root is the API root: https://api.github.com, or <gitea>/api/v1.
	root string
	// authorize returns the request authenticator, ErrNoWriter when the writer has no credential,
	// or the error of a token that could not be had (nothing was sent).
	authorize func(context.Context) (func(*http.Request), error)
	// removeLabel removes one label from an issue.
	removeLabel func(ctx context.Context, e *issueWriter, auth func(*http.Request), w Write) Result
	// listing is the first page of every issue changed since a time, and apiRoot, when set, is
	// what a next link is read under (Gitea writes its links from its public address).
	listing  func(e *issueWriter, src Source, since time.Time) string
	apiRoot  string
	maxPages int
	now      func() time.Time
}

// lookupSkew is taken off the time a create was sent when listing for its marker, for the
// difference between this node's clock and the forge's.
const lookupSkew = 5 * time.Minute

func (e *issueWriter) issues(src Source) string {
	return fmt.Sprintf("%s/repos/%s/%s/issues", e.root, url.PathEscape(src.Owner), url.PathEscape(src.Repo))
}

func (e *issueWriter) issue(w Write) string {
	return fmt.Sprintf("%s/%d", e.issues(w.Source), w.Number)
}

// issueRef is the part of an issue's JSON the writer reads.
type issueRef struct {
	Number    int    `json:"number"`
	HTMLURL   string `json:"html_url"`
	Body      string `json:"body"`
	State     string `json:"state"`
	Assignees []struct {
		Login string `json:"login"`
	} `json:"assignees"`
	PullRequest *struct{} `json:"pull_request"`
}

type labelRef struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

func (e *issueWriter) Write(ctx context.Context, w Write) Result {
	if err := w.validate(); err != nil {
		return Result{Outcome: OutcomeFailed, Err: err}
	}
	auth, err := e.authorize(ctx)
	if err != nil {
		if errors.Is(err, ErrNoWriter) {
			return Result{Outcome: OutcomeFailed, Err: err}
		}
		// Nothing was sent, so even a create is safe to try again.
		return Result{Outcome: OutcomeRetry, Err: err}
	}
	switch w.Action {
	case ActionCreate:
		return e.create(ctx, auth, w)
	case ActionAddLabel:
		return e.addLabel(ctx, auth, w)
	case ActionRemoveLabel:
		return e.removeLabel(ctx, e, auth, w)
	case ActionAddAssignee:
		return e.addAssignee(ctx, auth, w)
	case ActionRemoveAssignee:
		return e.send(ctx, auth, http.MethodDelete, e.issue(w)+"/assignees", map[string]any{"assignees": []string{w.Login}}, false)
	case ActionClose:
		return e.send(ctx, auth, http.MethodPatch, e.issue(w), map[string]string{"state": "closed"}, false)
	case ActionReopen:
		return e.send(ctx, auth, http.MethodPatch, e.issue(w), map[string]string{"state": "open"}, false)
	}
	return Result{Outcome: OutcomeFailed, Err: fmt.Errorf("unknown action %q", w.Action)}
}

// send makes a call whose 2xx alone is the confirmation.
func (e *issueWriter) send(ctx context.Context, auth func(*http.Request), method, url string, body any, create bool) Result {
	r := call(ctx, e.http, auth, method, url, body)
	if !r.ok() {
		return r.failure(create)
	}
	return applied(r.Status)
}

// create posts the issue with the marker at the end of its body. A 2xx that cannot be read into
// an issue number is UNKNOWN: the issue exists, and the marker search finds it.
func (e *issueWriter) create(ctx context.Context, auth func(*http.Request), w Write) Result {
	body := Marker(w.OutboxID)
	if w.Body != "" {
		body = w.Body + "\n\n" + body
	}
	r := call(ctx, e.http, auth, http.MethodPost, e.issues(w.Source), map[string]string{"title": w.Title, "body": body})
	if !r.ok() {
		return r.failure(true)
	}
	var made issueRef
	if err := json.Unmarshal(r.Body, &made); err != nil || made.Number <= 0 {
		return Result{Outcome: OutcomeUnknown, Status: r.Status, Err: errors.New("the forge answered 2xx without an issue number")}
	}
	return Result{Outcome: OutcomeApplied, Status: r.Status, Number: made.Number, URL: made.HTMLURL}
}

// addLabel posts the name. A label already on the issue is no error on either forge, and the
// answer, the issue's labels, is the proof: Gitea drops a name no label has and still answers
// 200, so a 2xx alone does not say the label is there.
func (e *issueWriter) addLabel(ctx context.Context, auth func(*http.Request), w Write) Result {
	r := call(ctx, e.http, auth, http.MethodPost, e.issue(w)+"/labels", map[string]any{"labels": []string{w.Label}})
	if !r.ok() {
		return r.failure(false)
	}
	var labels []labelRef
	if err := json.Unmarshal(r.Body, &labels); err != nil {
		return Result{Outcome: OutcomeRetry, Status: r.Status, Err: errors.New("the forge answered 2xx without the issue's labels")}
	}
	if !hasLabel(labels, w.Label) {
		return failed(r.Status, "the forge did not put label %q on the issue: no such label", w.Label)
	}
	return applied(r.Status)
}

// addAssignee posts the login. A user who cannot be assigned is ignored by GitHub and refused or
// ignored by Gitea, so the issue in the answer is the proof.
func (e *issueWriter) addAssignee(ctx context.Context, auth func(*http.Request), w Write) Result {
	r := call(ctx, e.http, auth, http.MethodPost, e.issue(w)+"/assignees", map[string]any{"assignees": []string{w.Login}})
	if !r.ok() {
		return r.failure(false)
	}
	var issue issueRef
	if err := json.Unmarshal(r.Body, &issue); err != nil {
		return Result{Outcome: OutcomeRetry, Status: r.Status, Err: errors.New("the forge answered 2xx without the issue")}
	}
	for _, a := range issue.Assignees {
		if strings.EqualFold(a.Login, w.Login) {
			return applied(r.Status)
		}
	}
	return failed(r.Status, "the forge did not assign %q: not an assignable user", w.Login)
}

func hasLabel(labels []labelRef, name string) bool {
	for _, l := range labels {
		if strings.EqualFold(l.Name, name) {
			return true
		}
	}
	return false
}

// issueLabels reads every label of an issue.
func (e *issueWriter) issueLabels(ctx context.Context, auth func(*http.Request), first string) ([]labelRef, reply) {
	return getAll[labelRef](ctx, e, auth, first, 10)
}

// getAll reads a paged listing into one slice. A page that fails, cannot be decoded, or a listing
// that does not end within maxPages comes back as a reply that is not ok, never as a short list.
func getAll[T any](ctx context.Context, e *issueWriter, auth func(*http.Request), first string, maxPages int) ([]T, reply) {
	base, err := url.Parse(e.root)
	if err != nil {
		return nil, reply{Err: fmt.Errorf("parse base url: %w", err)}
	}
	var all []T
	next := first
	var last reply
	for pages := 0; next != ""; pages++ {
		if pages == maxPages {
			last.Err = fmt.Errorf("more than %d pages", maxPages)
			return nil, last
		}
		last = call(ctx, e.http, auth, http.MethodGet, next, nil)
		if !last.ok() {
			return nil, last
		}
		var page []T
		if err := json.Unmarshal(last.Body, &page); err != nil {
			last.Err = fmt.Errorf("decode page: %w", err)
			return nil, last
		}
		all = append(all, page...)
		link := ""
		if m := nextLink.FindStringSubmatch(last.Header.Get("Link")); m != nil {
			link = m[1]
		}
		if next, err = nextOnBase(base, link, e.apiRoot); err != nil {
			last.Err = err
			return nil, last
		}
	}
	return all, last
}

// FindCreated lists every issue changed since the create was sent and matches the whole marker
// on the body. A listing is read, not a search: a search index can lag or be off, and "not found"
// is what lets the worker open a second issue.
func (e *issueWriter) FindCreated(ctx context.Context, lk Lookup) (LookupResult, error) {
	if err := lk.validate(); err != nil {
		return LookupResult{}, err
	}
	auth, err := e.authorize(ctx)
	if err != nil {
		return LookupResult{}, err
	}
	issues, r := getAll[issueRef](ctx, e, auth, e.listing(e, lk.Source, lk.SentAt.Add(-lookupSkew)), e.maxPages)
	if !r.ok() {
		if r.Err != nil {
			return LookupResult{}, fmt.Errorf("list %s for the marker: %w", lk.Source, r.Err)
		}
		return LookupResult{}, fmt.Errorf("list %s for the marker: %w", lk.Source, r.statusError())
	}
	marker := Marker(lk.OutboxID)
	var found LookupResult
	for _, it := range issues {
		if it.PullRequest != nil || !strings.Contains(it.Body, marker) {
			continue
		}
		// Two issues with the marker is not a state the writer makes; the first one opened is the create.
		if !found.Found || it.Number < found.Number {
			found = LookupResult{Found: true, Number: it.Number, URL: it.HTMLURL}
		}
	}
	if found.Found {
		return found, nil
	}
	if until := lk.SentAt.Add(lk.Settle); e.now().Before(until) {
		return LookupResult{}, &NotSettledError{Until: until}
	}
	return LookupResult{}, nil
}
