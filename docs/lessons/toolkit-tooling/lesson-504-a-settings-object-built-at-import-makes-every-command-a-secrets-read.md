---
id: lesson-504-a-settings-object-built-at-import-makes-every-command-a-secrets-read
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, python, sops, import-time]
---

# A settings object built at import makes every command a secrets read

**Context**: `toolkit/config/settings.py` ended in `settings = get_settings()`.
Building settings decrypts `common.enc.yaml` and `dev.enc.yaml` and copies every
string value (668 of them) into `os.environ`. BACKUP-071 ran a drill on ace2, a
host with no sops binary and no age key, feeding it inputs on stdin. The drill
printed `SOPS is not installed` twice before doing anything (#2021).

**Problem**: Every command, `--help` included, decrypted two SOPS files before
parsing its arguments, and every child process it spawned inherited the result.
Making `settings` lazy was the easy half. The hard half was the code that
depended on the eager build without referencing it, and none of it raised once
the build stopped:

- The logger read `log_level` and `log_format` from settings at import. It ran at
  `DEBUG` with the `json` format only because `dev.yaml` and `common.yaml` had
  been loaded before the first log line.
- `DockerHubClient.from_env()` read `DOCKERHUB_*` from `os.environ`. On a
  workstation those were there only because of the import-time injection.
- Four module-level singletons built in their constructors read
  `settings.project_root`, and one built a `ConfigurationManager`.

**Solution**: Make `settings` a proxy that forwards attribute reads and writes to
`get_settings()` for the environment resolved at import. Invert the logger's
dependency: `get_settings()` configures the logger when it builds the
import-time environment's settings. Then find the readers two ways:

- A subprocess test patches `ConfigurationManager.__init__` to raise and then
  imports `toolkit.main`. Each traceback names one import-time reader; fix it and
  rerun until the import succeeds.
- For the readers that fail silently, intersect the keys the toolkit reads from
  `os.environ` with the keys `get_env_vars()` injects (names only). That found
  `DOCKERHUB_*`, which now builds settings itself when CI has not set them.

**Why**: An eager global turns every implicit dependency on it into an ordering
accident that works. Laziness removes the accident, and only a dependency that
raises shows itself. A value that comes from an environment variable, or a log
level, quietly falls back to its default. Those have to be searched for. See
[[lesson-502-a-patch-applied-after-import-cannot-see-what-the-import-did]] for
the same import-time trap seen from the test side.
