---
id: lesson-461-grafana-re-runs-the-role-path-on-an-empty-groups-list
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, grafana, oidc, jmespath]
---

# Grafana re-runs the role path on an empty groups list, so a null guard on `groups` alone still answers from the ID token

**Context**: #1818 wrote Grafana's role path so that it returns null when the ID
token has no `groups`: ``groups != `null` && (contains(groups, 'admins') && 'Admin' || 'Viewer') || `null` ``.
The intent was that Grafana would then read the role from UserInfo, where Authelia
4.39 puts `groups` (lesson-457). Once OIDC was Grafana's only login (#1825, staging,
2026-09-24), `operator` and `manu`, both in `admins`, logged in through OAuth and came
out **Viewer**. `make auth-review ENV=staging` measured it.

**Problem**: Grafana 13.0.2 runs `searchRole` on each source in order: ID token, then
UserInfo, then access token. It keeps the first non-empty role, and it tries two
documents per source (`pkg/login/social/connectors/social_base.go`):

1. the source's own JSON;
2. if that finds nothing, `{"groups": []}`, an empty list hardcoded in the call
   (`generic_oauth.go`, `extractRoleAndAdminOptional(data.rawJSON, []string{})`).

So for every source whose JSON does not decide the role, the path is also run on
`{"groups": []}`. The path treated an empty list as "no admin, so Viewer", on
purpose: its comment said that "an empty list must still yield 'Viewer'". So it
answered 'Viewer' on the second try, the role was set on the ID token, and UserInfo
was never consulted for it. The unit test even asserted `{"groups": []} → "Viewer"`.
It was right about JMESPath and wrong about Grafana, because it evaluated the path
against the documents we imagined, not the ones Grafana builds.

**Solution**: ``length(groups || `[]`) > `0` && (contains(groups, 'admins') && 'Admin' || 'Viewer') || `null` ``.
It returns null for a missing list and for an empty one, and it never raises an error
on a missing field. `tests/test_access_review.py` now replays Grafana's two searches
per source (`_grafana_role`) instead of evaluating the expression once.

A consequence to know: when no source yields a role, Grafana does not leave the role
alone. `MapOrgRoles` falls back to `auto_assign_org_role`, Viewer by default, and the
login syncs it (`org_role_mapper.go`, `getDefaultOrgMapping`). So a user in no group,
or an admin whose UserInfo came back without `groups`, is set to Viewer at that login.
That errs towards less privilege, never more.

**Rule**: To test a claim mapping, replay what the consumer evaluates, not the
expression alone. Find in the version you run which documents the path is run
against, in what order, and what counts as "not found". A fallback the consumer
builds itself, like Grafana's `{"groups": [...]}`, is an input nobody writes down,
and it is the one that decided the outcome here.

**Tags**: `#grafana` `#oidc` `#jmespath` `#role-mapping` `#auth-004`
