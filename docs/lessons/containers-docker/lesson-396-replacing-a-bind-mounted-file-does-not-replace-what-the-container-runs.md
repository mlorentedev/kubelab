---
id: lesson-396-replacing-a-bind-mounted-file-does-not-replace-what-the-container-runs
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ansible, idempotence, gitea]
---

# Replacing a bind-mounted file does not replace what the container runs, and an unrelated bug was hiding it

**Context**: ANSIBLE-054 (#1400). The Beelink's Gitea bootstrap reported a
change on every provision, so the handler restarted the forge every time. The
fix made the report conditional. Two consecutive provisions were then expected
to show `changed=0`, and the second one still said `changed=2`.

**Problem**: The first reading was "the fix does not work". It was wrong on both
halves — the fix was correct, and the script being executed was not the one that
had just been installed.

The compose file mounts the script as a single **file**:

```yaml
- {{ beelink_deploy_dir }}/gitea-bootstrap.sh:/scripts/bootstrap.sh:ro
```

A single-file bind mount pins the **inode**. Ansible's `copy` writes a temporary
file and renames it into place, so the host path gains a *new* inode while the
running container keeps the old one, and Docker re-resolves mounts only when a
container starts. The timeline is unambiguous:

```
run 1  finished 01:51:36Z    bootstrap reported changed
marker written 01:53:16Z     <- during run 2, not run 1
run 2  finished 01:53:41Z    bootstrap reported changed
run 3  changed=0
```

Run 1 installed the new script and then executed the previous one. Run 1's own
`Restart gitea` handler re-resolved the mount, which is why run 2 was the first
run to execute what run 1 had delivered.

**The part worth the lesson is why this had never been seen.** The old script
announced `Updated` on *every* provision, so the container was restarted every
time — by accident — and the accident kept the mount fresh. Removing the noise
removed the mechanism that had been papering over the delivery bug. A defect can
be load-bearing, and fixing an unrelated one is how you find out.

**Solution**: `notify: Restart gitea` on the task that installs the script, so
delivery and activation are one step. Guarded by a test that reads the task out
of `tasks/main.yml` and asserts the notify, because the coupling is invisible in
the file itself — nothing about a `copy:` task says the container mounts its
target. After the change the transition is bounded at two runs and each one
names what it did:

```
run 1  changed=2   Install Gitea bootstrap script  +  Restart gitea
run 2  changed=2   Bootstrap Gitea admin user...   +  Restart gitea
run 3  changed=0
```

A corollary from the same session, on choosing the field that moves: the
acceptance criterion asked to prove the restart through the container's
*restart count*. `docker restart` does not increment `RestartCount` — that
counter is Docker's restart-*policy* bookkeeping. It read `0` before and `0`
after, across a session in which the handler had restarted the container
repeatedly. `State.StartedAt` is the field that moves (`01:53:37Z` →
`02:14:26Z`). A criterion written against the wrong field does not fail; it
passes silently having measured nothing.

**Rule**: Bind-mount the **directory**, not the file, when something replaces
the file in place — or make the replacing task restart the container, and pin
that with a test. And when a change appears to have no effect, verify it is
*live at the moment of measurement* before concluding it is wrong: "no effect"
and "not deployed" are indistinguishable from the outside, and on the Docker
path the delivery is the likelier of the two. Same shape as lesson-330 on the
Argo CD path.

**Tags**: `#docker` `#bind-mount` `#ansible` `#idempotence` `#pr-1421`
