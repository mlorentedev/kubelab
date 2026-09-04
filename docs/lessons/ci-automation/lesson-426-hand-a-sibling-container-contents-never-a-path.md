---
id: lesson-426-hand-a-sibling-container-contents-never-a-path
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gitea, act-runner, docker, tool-035]
---

# Hand a sibling container contents, never a path

**Context**: Porting `resume`'s six-job `ci.yml` to Gitea Actions on `act_runner`
(TOOL-035 AC6). The workflow ran unchanged on GitHub for months.

**Problem**: Three separate steps broke, and they looked like three unrelated bugs.

```
test        green, having run almost nothing
build-pdf   ! I can't find file `cv-manuel-lorente-alman.tex'
audit       Could not find the file /work in container
```

They are one defect. **On a self-hosted runner the job container's filesystem is
not the daemon's filesystem.** act_runner gives the job a named Docker *volume* as
its workspace and mounts the host's socket into it, so every `docker run` the job
issues is executed by the daemon on the **host**, which resolves paths in its own
filesystem and has never heard of `/workspace/personal/resume`.

On GitHub-hosted runners the job and the daemon share a machine, so `-v "$PWD/x"`
works and nothing in the workflow records that it depends on that.

The three costumes:

| Step | What it handed over | What the daemon did |
|---|---|---|
| `docker run -v "$PWD/data:/app/data:ro"` | a path | created an empty directory |
| `resume build --in-docker` (binds `dist/<tpl>`) | a path, indirectly | started xelatex in an empty directory |
| `docker cp file cid:/work/...` | a path *into* a container | 404 — the image has no `/work` |

**The first one is the dangerous one.** Docker creates the missing directory
rather than failing, the four data-dependent test modules `skipif` themselves out,
and the job reports **green having tested almost nothing**. The second failed red
only by luck: a stale `.tex` would have shipped an out-of-date PDF and passed.

**Solution**: Hand over the CONTENTS.

```bash
cid=$(docker create <image> sh -c 'test -s /app/data/cv.yml || { echo "::error::..."; exit 1; }; make test')
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
docker cp data/. "$cid":/app/data
docker start --attach "$cid"
```

Two details that are not incidental:

- **The container asserts the files arrived**, because the failure mode is a green
  job. A guard that only runs the suite would still pass on an empty mount.
- **`docker cp` does not create parent directories.** Target a path the image
  already has (`/tmp`), or the copy 404s before the tool runs — which is the third
  instance above, produced while fixing the second.

**Rule**: On any runner where the job is a container and the daemon is on the
host, **a path is not a shared reference — only bytes are**. Before writing a
`docker` invocation in CI, ask *whose filesystem resolves this string*. If the
answer is "the daemon's" and the file was written by the job, the step is broken.

Verify by consequence and not by the check: read the collected/skipped counts, or
assert the artifact count. `test` went from a green run to `collected 725 items,
722 passed, 3 skipped` — the three being `not a git checkout`, none of them the
four modules the bind had been silently disabling.

Two more incompatibilities from the same port, unrelated to this rule but worth
finding here: `actions/upload-artifact@v4` refuses Gitea with
`GHESNotSupportedError` (use `@v3`), and `aquasecurity/trivy-action` is a
composite that clones its installer from github.com, which a forge-scoped
credential cannot do — run the pinned image directly.

Related: [[lesson-424-a-convergence-step-scoped-to-the-creation-diff-repairs-nothing]]
and [[lesson-425-a-capability-probe-can-stop-at-the-first-authorization-layer]].

**Tags**: `#gitea-actions` `#act-runner` `#docker` `#ci` `#tool-035`
