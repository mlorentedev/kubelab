---
id: lesson-551-authelia-merges-config-files-but-a-list-lives-in-exactly-one-of-them
type: lesson
status: active
created: "2026-09-22"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, authelia, oidc, ssot]
---

# Authelia merges config files, but a list lives in exactly one of them

**Context**: SSOT-017 moved the OIDC client list out of the hand-written
`configuration.yml` and into a generated `oidc-clients.yml`, rendered from
`apps.services.security.authelia.oidc_clients`. The plan relied on Authelia 4.39
loading several configuration files and merging them.

**Problem**: Authelia does merge several files, but it does not combine lists
across them. A `clients:` list split between two files is not one list of both
halves, so the whole list has to live in the generated file, and
`configuration.yml` must carry no `clients:` key at all. Which files load is a
second trap. The `authelia/authelia:4.39.15` image has no `CMD`, and its
`entrypoint.sh` passes no `--config`, so the file list is the container's
`X_AUTHELIA_CONFIG`. A manifest that mounts the second file and leaves that
variable at its default reads correctly and loads one file.

**Solution**: `configuration.yml` in the base and the prod overlay has no
`clients:` key, and the Deployment sets `X_AUTHELIA_CONFIG` to both paths. The
load was proven by consequence, not by reading the manifest:
`authelia validate-config` on the rendered staging ConfigMap with
`configuration.yml` alone failed with `option 'clients' must have one or more
clients configured`, and with both files that error was gone.
`tests/test_oidc_clients.py::test_authelia_config_split` holds the split, and
dropping the second path from `X_AUTHELIA_CONFIG` turns it red.

**Rule**: When you split one config across files, find out how the program
merges a list before you split one, and prove which files it loads by making it
fail on the file it should not need. A mounted file the process never reads
looks the same as one it does.

**Tags**: `#authelia` `#oidc` `#ssot-017` `#pr-1780`
