---
id: lesson-724-a-fail-closed-parse-after-a-successful-mutation-reports-the-opposite
type: lesson
status: active
created: "2026-11-07"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, headscale, fail-closed]
---

# A fail-closed parse after a successful mutation reports the opposite of what happened

**Context**: Minting the `tenant-1` pre-auth key for pxn-edge-01 through `make headscale-authkey` (VPN-ACL-016, #2863) — the last step of the tenant-onboarding runbook, against headscale v0.28 in Docker on the VPS.

**Problem**: The mint aborted with `could not parse headscale create output (not JSON); key not delivered`, and the key had been created. `--output` is a **global** headscale flag whose default is human-readable text; `users list` in the same module carried `--output json` and `preauthkeys create` did not. So the create ran, printed prose, and `parse_create_output` — correctly fail-closed, correctly refusing to echo what it could not parse — turned a success into a reported failure. `preauthkeys list` showed id 111, single-use, 1 h TTL, correct tag: real, and unreachable, because its material was never captured. Every retry would leave another. The unit tests mocked JSON for the create call, so no test could see this; the module's own docstring called the output shape "unverified against the running binary", which is exactly where e2e validation was mandatory and had not been run.

**Solution**: One line, symmetric with the neighbouring call — `f"preauthkeys create {create_command} --output json"`. The key was minted by hand meanwhile (`docker exec headscale headscale preauthkeys create --user 5 --expiration 1h --tags tag:pixelnam-lab --output json`, piped straight into an owner-only file so the material never reached a terminal), and the fix was then proved end-to-end against the running binary: a real mint through the toolkit answered `[SUCCESS] minted pre-auth key 113 … expires 1h`, exit 0, and the delivered file was shredded. A regression test asserts the flag is in the built command (#3195).

**Rule**: A fail-closed parse protects the caller from garbage; it says nothing about the world. When the parsed output comes from a command that *mutates*, a parse failure does not mean "nothing happened" — it means "something happened and I cannot see it", and the operator will read it as the former. So: make the error say so (`could not parse …; the key may exist — check preauthkeys list`), and make the side effect self-expiring or idempotent so an unreadable attempt costs nothing. Separately, a mocked-output test proves the parser and never the call — where a docstring admits "unverified against the running binary", that sentence is the e2e test's ticket.

**Tags**: `#toolkit` `#headscale` `#fail-closed` `#pr-3195` `#issue-2863`
