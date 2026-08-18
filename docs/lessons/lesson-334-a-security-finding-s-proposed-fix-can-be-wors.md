---
id: lesson-334-a-security-finding-s-proposed-fix-can-be-wors
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, security, code-review, adversarial-review, bash, false-positive, ansible-035]
---

# A security finding's proposed fix can be worse than the bug it invents — reproduce before remediating

**Context:** ANSIBLE-035's adversarial review returned three Minor findings against the maintenance notify script. One was filed under **Security**: `TOKEN="$(cat /opt/...-secret)"` followed by `curl -H "Authorization: Bearer ${TOKEN}"`, flagged as a shell-injection surface — "if the secret file were tampered with to contain `$(...)`, backticks, or shell metacharacters, injection is possible". Recommended fix: read the token via `curl --config <file>` instead.

**The trap:** the finding is wrong, and applying its fix would have made the system less safe. Bash does not re-parse the *value* of a variable expanded inside double quotes — no command substitution, no word splitting, no globbing. Measured directly:

```
$ cat /tmp/tok-test
$(touch /tmp/PWNED-should-not-exist)`touch /tmp/PWNED2-should-not-exist`
$ TOKEN="$(cat /tmp/tok-test)"; set -- -H "Authorization: Bearer ${TOKEN}"
  [Authorization: Bearer $(touch /tmp/PWNED-should-not-exist)`touch ...`]
PWNED files created? -> 0
```

Passed through as a literal; nothing ran. The finding reasons by analogy with `eval`, which this path does not use. Meanwhile its remedy — `curl --config <file>` — would have written a live fleet-wide bearer token to a file on disk, to defend against an attack that does not exist.

The **Security** label is what makes this dangerous. A Minor labelled *reliability* invites a cost/benefit argument; a Minor labelled *security* invites compliance, and "it's cheap, just apply it" is the path of least resistance for both a human and an agent.

**Fix:** reproduce the exploit before writing the patch. Two of the three findings reproduced (a real `UnicodeDecodeError` from a byte-truncated UTF-8 sequence, and curl's missing timeouts) and were fixed; this one did not, and was refuted in writing on the ticket with the transcript above. A regression test now pins the property from the other direction — `test_token_value_is_not_shell_interpreted` fails if anyone later "hardens" the line into an `eval` or an unquoted expansion, which is where the risk actually lies.

**Rule:**
- **Reproduce a vulnerability before remediating it.** A finding is a hypothesis. If you cannot make the exploit fire in a scratch shell, you do not yet know what you are fixing — and you cannot judge whether the proposed remedy is proportionate.
- **Read the proposed fix as adversarially as the finding.** Ask what the remedy itself costs. Moving a secret from a process argument to a file on disk is not obviously an improvement; here it was a regression.
- **When you decline a finding, leave the evidence where the finding lives** — on the ticket, and as a test. "We looked at it and it's fine" is indistinguishable from "we never looked", three months later.

**Tags:** `#security` `#code-review` `#adversarial-review` `#bash` `#false-positive` `#ansible-035`
