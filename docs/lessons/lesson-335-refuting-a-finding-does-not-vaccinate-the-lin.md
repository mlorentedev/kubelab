---
id: lesson-335-refuting-a-finding-does-not-vaccinate-the-lin
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, security, code-review, adversarial-review, reasoning, ansible-035, ansible-038]
---

# Refuting a finding does not vaccinate the line it was about

**Context:** immediately after the refutation above, round 2 of the same review examined the same two lines and found something else: the bearer token *is* exposed, just not the way round 1 claimed. `-H "Authorization: Bearer ${TOKEN}"` becomes an argv element of `curl`, so it is readable in `/proc/<pid>/cmdline` and `ps` output for roughly a second per invocation.

**The trap:** having just proved — correctly, with a transcript — that the token is not shell-injectable, the natural reading of any further concern about that line is "we already settled this". The two findings share a file, a line, and a credential. They do not share a mechanism: one is about whether the shell *re-parses the value*, the other about *where the value ends up* once it is an argument. The first question being answered says nothing about the second.

The refutation was not wrong. Its scope was narrower than it felt.

**Fix:** treat a refutation as closing exactly one attack path, never the line. Recorded on #1088 with the distinction spelled out, and fixable without reintroducing the on-disk problem the round-1 remedy would have caused — fed from a pipe, the token appears in neither argv nor any file, which is what round 1 was reaching for and got wrong by choosing a file.

**Correction, when the fix was actually implemented (same day).** This entry originally published the one-liner below as the fix. **Do not use it as written** — it silently corrupts the credential:

```sh
# WRONG — loses everything from the first `"` in the token
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl --config - ...
```

curl's config parser processes `\` and `"` *inside* a quoted value. Measured against a local listener, a token containing `"` arrived as `Authorization: Bearer tok`; dropping the quotes instead made curl send no `Authorization` header at all. Both outcomes are a 403 from the far end, i.e. the notification is lost — strictly worse than the ~1s of `ps` exposure being fixed. The shipped form escapes first:

```sh
TOKEN_ESC=${TOKEN//\\/\\\\}
TOKEN_ESC=${TOKEN_ESC//\"/\\\"}
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN_ESC" | curl --config - ...
```

**Rule:**
- **State what a refutation covers, in mechanism terms, not in location terms.** "Not shell-injectable" is a claim about parsing. "This line is fine" is a claim about everything, and you did not test everything.
- **Expect the second finding on code you just defended.** Successfully arguing against a reviewer is precisely the state in which the next concern about that code gets waved through.
- **A correct fix for a wrong finding can still be the right fix later.** Round 1's `curl --config` was disproportionate to a nonexistent bug, and its piped form is proportionate to a real one. Reject the reasoning without discarding the technique.
- **Moving a secret between transports moves its escaping problem too, and the new parser is rarely the one you were thinking about.** argv needed shell quoting; a curl config needs curl's own quoting. This lesson published an unescaped form as settled *because the security question it was reasoning about had been settled* — the transport question underneath it had not been asked.
- **A remediation deserves the same reproduction as the finding.** Both findings here were reproduced before being accepted or refuted; the *fix* was not, until it was implemented. That asymmetry is where this entry went wrong.

**Tags:** `#security` `#code-review` `#adversarial-review` `#reasoning` `#ansible-035` `#ansible-038`
