---
id: lesson-374-grepping-an-output-that-was-never-produced
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, measurement, gitea, docker]
---

# Grepping an output that was never produced

**2026-08-23** — measuring AUTH-004's open risks against the live Gitea on the Beelink.

## What happened

AUTH-004's R5 asks whether Gitea can derive the admin bit from an OIDC group
claim, and the spec is explicit about how to answer it: *"settle against the live
binary's `--help`, not the docs"*. So the probe was a `--help` piped into a grep:

```bash
docker exec gitea gitea admin auth add-oauth --help | grep -iE "admin|group|claim" \
  || echo "(no admin/group/claim flags)"
```

It printed `(no admin/group/claim flags)`, and that was read as the answer: Gitea
cannot map an admin group, so the superadmin tier is a provisioning step rather
than a claim mapping. That conclusion would have redirected the whole of ADR-062's
identity model.

The command had never run:

```
[F] Gitea is not supposed to be run as root. Sorry.
```

`docker exec` enters as root, Gitea refuses to start as root, and the grep was
searching an error message. Re-run as `-u git`, the same command returns
`--group-claim-name`, `--admin-group`, `--restricted-group` and `--group-team-map`.
**The true answer was the exact opposite of the recorded one.**

The same shape recurred fifteen minutes later, on a different question. A probe for
the admin API's `prohibit_login` field fetched the OpenAPI schema from inside the
node:

```
$ curl -s http://localhost:3000/swagger.v1.json > /tmp/sw.json
swagger bytes: 0
```

Zero bytes reads as "this instance does not publish a schema". It is not: the
compose file binds Gitea to `{{ tailscale_ip }}:3000` rather than to loopback,
because a published port is governed by its bind address and nothing else. From
`100.64.0.3:3000` the same request returns **816 KB** and answers the question.

## Why it survived

Both failures produce the *shape* of a negative result. A grep with no match and a
download of zero bytes are both indistinguishable, at the point of reading, from a
successful measurement that found nothing — and "found nothing" was a plausible
answer to both questions. Nothing errored, nothing was red, and the `|| echo`
fallback actively dressed the failure as a finding.

What caught the first one was not diligence. It was that the wrong answer
**contradicted a record**: R5 had already been settled on 2026-08-15 with a full
transcript, and the duplicate probe disagreed with it. Without that prior entry the
inverted answer would have gone into the spec.

## The rule

**Grepping an output without establishing that the output exists is not a
measurement.** A filter applied to a stream nobody verified reports on the filter,
not on the system.

Every read-only probe needs a **control that fails loudly** — a call whose success
is unambiguous, run first, against the same channel:

```bash
curl -s --max-time 10 http://100.64.0.3:3000/api/v1/version   # {"version":"1.25.5"}
```

If the control does not answer, nothing downstream of it is a result. Prefer
capturing the full output and asserting on it over `cmd | grep … || echo "none"`,
which cannot tell an empty match from an empty stream.

## Where this has bitten before

This is the same family, and the list is now long enough to be the point:

- `dig … && echo YES` — `dig` exits 0 on SERVFAIL, so the `&&` fires on a failed
  lookup.
- `make x | tail` — the pipe swallows the exit code; an Ansible failure reported
  "exited with code 0".
- **An absent log line is not a negative result** — two marked probes returned zero
  on *both* hubs, because `argocd-server` logs events rather than requests
  ([[lesson-370]]).
- `--optional` on `render-apply` reported SUCCESS on a failed render.
- A test that matched a template's **comment** rather than its code.
- [[lesson-371]] — absence from a bounded query is not evidence of absence.

Those are about a channel that answered wrongly. This one is narrower and easier to
miss: **the channel did not answer at all, and the wrapper supplied a sentence
anyway.**

## See also

- `specs/AUTH-004-identity-and-machine-access/verification.md` — the R4 entry, with
  both transcripts
- [[lesson-371]] — the truncated-listing case, same week
- [[lesson-372]] — `Synced`/`Healthy` over an empty history
