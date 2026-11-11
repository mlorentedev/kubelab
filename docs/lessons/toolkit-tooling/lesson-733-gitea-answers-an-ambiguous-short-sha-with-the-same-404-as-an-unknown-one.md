---
id: lesson-733-gitea-answers-an-ambiguous-short-sha-with-the-same-404-as-an-unknown-one
type: lesson
status: active
created: "2026-11-10"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, gitea, forge-adapter]
---

# Gitea answers an ambiguous short sha with the same 404 as an unknown one

**Context**: Writing the Gitea half of the forge adapter (IDP-053, #2612): the four reads the product path asks of a product's repository (`resolve_commit`, `is_on_default_branch`, `read_file`, `resolve_tag`). Measured 2026-11-10 against a disposable gitea/gitea:1.27.3 (`REQUIRE_SIGNIN_VIEW=true`, the prod shape), a public repository `personal/example-app` of 151 commits with a lightweight tag, an annotated tag, a second branch and a branch named `rel/next`, read with a token holding `read:repository` and nothing else. The instance and every credential were throwaway.

**Problem**: GitHub tells "no such commit" from "more than one commit starts with this" in the status line's text. Gitea does not, and three other answers differ from what the GitHub calls would suggest:

| Adapter method | Endpoint (all `GET`, `/api/v1/repos/{o}/{r}` prefix) | What was measured |
|---|---|---|
| `resolve_commit` | `/git/commits/{short}` | 200 with `.sha` for a unique prefix of 4 or more hex digits. **404 `commit doesn't exist: <short>` for an unknown prefix AND for an ambiguous one**, with a byte-identical body, so the answer cannot tell them apart. Under 4 digits is a 404 even when unique. It also resolves **ref names**: `/git/commits/main` and `/git/commits/v1.1.0` answer 200 with that ref's commit, so a prefix that is really a branch name would pass unless the answer's sha is checked to start with it. A non-hex string is a 404. |
| (ambiguity probe) | `/git/commits/{short}{0-f}` | Extending the prefix by one digit resolves exactly the commits that continue it: for the ambiguous `f765`, `f765b` and `f765c` answered 200 and the other fourteen 404. So 404 on `{short}` plus at least one extension answering 200 is "ambiguous", and 404 plus none is "unknown". Two commits sharing one more digit than the probe adds both fail it and read as unknown; at 7 hex that needs a collision on 8, which a repository of this kind does not produce. |
| `is_on_default_branch` | `/` for `.default_branch`, then `/compare/{branch}...{sha}` | `compare` has **no `status` field** (GitHub's `identical`/`behind` has no analogue): it returns `total_commits` and `commits`, the commits in the head that the base lacks. `main...{sha}` gave `total_commits: 0` for the head itself and for an older commit (both on the branch) and `1` for a commit only a side branch holds. Reversed (`{older}...main`) it gave 148, the commits the older one lacks, so the direction is part of the answer: base is the branch, head is the sha. An unknown sha is a 404, a branch with a slash (`rel/next...{sha}`) works unencoded. |
| `read_file` | `/raw/{path}?ref={sha}` | 200 `text/plain` with the bytes, exactly. A missing file is a 404 `{"message":"not found"}`; an unknown ref is a 404 `unable to find a git ref`. Without `ref` it reads the default branch, so the adapter always sends one. `/contents/{path}` answers the same file as base64 inside JSON and reports a missing one as `object does not exist [id: , rel_path: ...]`; `/raw` is the one that needs no decoding. |
| `resolve_tag` | `/tags/{tag}` | 200 `{"name", "id", "commit": {"sha", "url"}}`. For an **annotated** tag `id` is the tag object's sha and **`commit.url` also names the tag object**, but `commit.sha` is the commit; for a lightweight tag the two are equal. Reading `.id`, or following `commit.url`, would hand the receiver a sha that is not a commit. A missing tag is a 404 `tag doesn't exist: <tag>`. `/git/commits/{tag}` also resolves a tag to its commit, but it resolves branches too, so it cannot say that what was named is a tag. |

Scope and auth, for the same calls: a token holding `read:user` only is refused 403 `required=[read:repository]` on every endpoint above, so the grant is `read:repository` and no other scope serves them. With `REQUIRE_SIGNIN_VIEW` a request with no token is 403 `Only signed in user is allowed to call APIs`, a wrong token is 401, and the same token reads a private repository's `/raw` (200).

**Solution**: `GiteaClient` gained `get_commit`, `compare_ahead`, `get_raw_file` and `get_tag`, each declared `read:repository` in `SCOPE_BY_METHOD` and none in `ADMIN_METHODS`, because the receiver reads with its own `repo_reader` token (S5c), not the reconciler's. `GiteaForge` makes the checks above: a resolved sha must start with the short one, an unresolved one is told apart by the one-digit probe, `compare`'s `total_commits` of 0 is "on the default branch", and a tag is read from `commit.sha`. Recorded responses in `tests/test_forge_adapter.py` carry the measured messages.

**Rule**: Measure the failure answers of a forge, not only the success ones: two failures that GitHub words differently may be one status and one body on Gitea, and the distinction then has to be rebuilt from further reads, with its blind spot stated. And never trust that a field named for a commit holds a commit until the annotated case has been read: Gitea's tag answer carries the tag object in three of its four places.

**Tags**: `#gitea` `#forge-adapter` `#measurement` `#issue-2612`
