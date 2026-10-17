---
id: lesson-453-an-absence-is-only-as-strong-as-the-search-that-produced-it
type: lesson
status: active
created: "2026-09-07"
owner: manu
category: process-method
tags: [kubelab, process-method, audit, terraform, verification, false-negative]
---

# An absence is only as strong as the search that produced it, and an audit is mostly absences

**Context**: Dispositioning the 58 findings of the multi-angle audit of
2026-09-07 — filing tickets, and re-measuring each high-severity finding before
writing its ticket rather than trusting the report.

**Problem**: Three separate negatives were produced in one session and **all
three were false**. Each was a well-formed answer from a search that could not
have found the thing it declared missing.

**First, the one that inverted a security finding.** The report asserted, for
`home.kubelab.live`:

> no Cloudflare record exists for it and no wildcard covers it

That came from reading `infra/terraform/dns/records_kubelab.tf`, which contains
no literal `home` — because it contains no literal service name at all:

```hcl
resource "cloudflare_record" "kubelab_services" {
  for_each = local.kubelab_services
```

The names live in `infra/terraform/dns/services.json`, where the record is
declared and from where it reached `terraform.tfstate`:

```json
{"name": "home", "zone": "kubelab", "proxied": false, "environments": ["prod"]}
```

The cost was not the wrong fact, it was the wrong *severity*. A second finding
(the Homepage cockpit has no Authelia middleware) had been graded "latent today"
**on the strength of that absence** — the hostname does not resolve, so the
missing auth cannot be exploited. Measured:

```
$ dig +short home.kubelab.live @1.1.1.1
162.55.57.175
$ curl -sI https://home.kubelab.live/ | head -1
HTTP/2 200
```

Live and unauthenticated, with `/api/services`, `/api/bookmarks` and
`/api/widgets` all answering 200. One false negative had downgraded a live
exposure to a hypothetical.

**Second, on the board.** A verifier for the 17 freshly-filed tickets reported
every one of them `NOT ON BOARD`. They were all on the board with all four
fields set. `gh project item-list --limit 1000` returns exactly 1000 items and
the highest issue number among them is `#775`; everything newer is silently
absent, with no truncation warning.

**Third, and this one was answered correctly, which is the point.** Deleting 20
uncalled functions rested on the same kind of claim — "nothing references this".
That one held, because the search was built to be falsifiable: every name
grepped across every `*.py` **including `tests/`**, and then the two private
helpers traced to their only caller before deleting them with it.

```
$ grep -rn "\b${fn}\b" --include='*.py' . | grep -v '\.venv/' | grep -v "^\./${f}:"
```

The confirmation was `2428 passed` — unchanged. If any had been referenced, the
suite would have said so.

**Solution**: For the DNS claim, read the artifact rather than the thing that
builds it — `terraform.tfstate` and `services.json`, not the `.tf`. For the
board, ask the issue for its project items instead of enumerating the project
([[lesson-452]]). For the deletion, make the negative falsifiable and then run
the thing that would falsify it.

**Rule**: **A negative is a claim about your search, not about the world.** An
audit is made almost entirely of negatives — "no record exists", "nothing
references this", "no test covers this", "this has no caller" — and a negative
never carries its own evidence the way a positive does. Finding a thing proves it
is there; not finding it proves only that you looked somewhere.

So before writing an absence into a report, name the search that would have found
it and check that the search *could* have. Two failure shapes cover most of it:

- **You read the generator instead of its output.** A `for_each`, a
  `configMapGenerator`, a template — grepping the source for a literal that only
  exists downstream returns a confident nothing. This repo already states the
  rule for Kustomize (*"verify by reading the emitted object, never the patch"*);
  the 2026-09-07 audit applied it to K8s and not to Terraform. It is one rule,
  not two.
- **You read a truncated view.** A capped listing, a stale working tree, a
  partial load — [[lesson-452]] in full.

**And weight the consequence, not just the fact.** The severity of a finding is
often *derived* from an absence ("latent because it does not resolve", "safe
because nothing calls it"). When the absence is wrong the fact is a footnote and
the grading is the damage — which is why the negatives worth re-measuring first
are the ones another finding leans on.

**Tags**: `#audit` `#verification` `#terraform` `#false-negative` `#pr-1758`
