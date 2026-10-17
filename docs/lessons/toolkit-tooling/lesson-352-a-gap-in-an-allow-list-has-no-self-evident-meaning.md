---
id: lesson-352-a-gap-in-an-allow-list-has-no-self-evident-meaning
type: lesson
status: active
created: "2026-08-19"
owner: manu
category: toolkit-tooling
tags: [toolkit, uptime-kuma, secrets, serialisation, config-as-code]
---

# A gap in an allow-list has no self-evident meaning — the same absence was the control in one list and the bug in the next

**Context**: Adding a `push` monitor to the declarative Uptime Kuma sync, as the
heartbeat half of a dead man's switch for the prod PVC backup. The session
handoff recorded the blocker precisely: *"`pushToken` is absent from
`_MONITOR_EXPORT_FIELDS`, so the config-as-code round-trip drops it"*, and the
task was to add it.

**Problem**: `pushToken` was absent from **two** allow-lists in the same feature,
with the same shape and opposite meanings.

In `_MONITOR_EXPORT_FIELDS` — which decides what `monitoring-export` writes into
`infra/config/uptime-kuma/monitors.json` — the absence **was the control.** That
file is committed to a public repository and the push endpoint is publicly routed
at `status.kubelab.live/api/push/<pushToken>`. Anyone holding the token can post
"still alive" to the monitor whose entire purpose is to notice silence, so an
exported token does not weaken the switch, it **inverts** it. Completing the
list, exactly as instructed, would have shipped a live credential into git and
turned a watchdog into a rubber stamp.

In `WRITABLE_FIELDS` — which decides what the diff compares — the same absence
was a real defect: a token rotated in the Kuma UI read as converged, so the
monitor reported UP forever having quietly stopped listening.

**Nothing about either gap says which it is.** Both are one missing string in a
`frozenset`. The first had no comment; it was indistinguishable from an
oversight, which is precisely why it was queued for "fixing".

A third absence was hiding underneath, and only measurement found it:

```python
# uptime_kuma_api/api.py — the token generator
def _convert_monitor_input(kwargs) -> None:
    if kwargs["type"] == MonitorType.PUSH and not kwargs.get("pushToken"):
        kwargs["pushToken"] = gen_secret(10)
```

`add_monitor()` calls that. The toolkit does not — it builds the payload with
`api._build_monitor_data(**params)` and then calls the raw socket, deliberately,
for a documented reason about v2 response handling. And `_build_monitor_data`
declares its parameters one by one, with **no `pushToken` among them**, so it
cannot be passed either. The result was a push monitor created with no token at
all — an endpoint nothing can post to — reported as a successful create.

**Solution**: Establish which kind of gap each one is, then treat them
differently.

- The export omission stays, and now says so in place: SOPS owns the value, the
  seed never carries it, and `hydrate_push_tokens` marries the two in memory at
  apply time. Export dropping the field is therefore **lossless** — the JSON was
  never where the value lived.
- `WRITABLE_FIELDS` gains the field, so drift is repaired.
- The create path pops the token before `_build_monitor_data` and sets it on the
  returned dict, the same idiom already used for `conditions`.
- Both directions fail closed: a declared push monitor with no token in SOPS
  refuses the sync rather than letting the library invent one, and an inline
  token in the seed is refused rather than quietly honoured.

**Rule**: An absent field in an allow-list carries no meaning by itself. Before
completing such a list, establish whether the gap is an oversight or a decision —
and if it is a decision, **write the reason where the gap is**, because the next
reader's default is "someone forgot".

- **A serialiser's allow-list is a disclosure boundary**, not a convenience. Any
  list that decides what reaches a committed file is deciding what reaches
  everyone who can read the repo, and an undocumented omission there is one
  tidy-up commit away from being a leak.
- **Bypassing a library's wrapper inherits the absence of every default it
  applied.** The reason for going around `add_monitor()` was sound and narrow;
  the cost was silent and wider. When you skip a wrapper, read what it did
  besides the thing you were avoiding.
- **Read the value's *other* consumer before choosing its name.**
  `ConfigurationManager._flatten_dict` joins SOPS paths with `_` and uppercases
  them without touching hyphens, so a kebab-case sub-key becomes an env var name
  `SECRET_DEFINITIONS` cannot consume. Found by looking downstream; left alone it
  would have surfaced two PRs later with the convention already committed.
- A handoff note describing a blocker is a **report of a symptom**, not a
  ratified diagnosis — even when the previous session wrote it carefully, and
  even when it is your own.

**Tags**: `#toolkit` `#secrets` `#config-as-code` `#issue-1169` `#issue-1171`
