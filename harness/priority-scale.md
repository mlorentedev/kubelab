# Priority scale (GOV-005, #1417)

What `P0`–`P3` mean on this board, so the next session doesn't have to re-derive
it from the live distribution. Mirrors the cross-repo rubric in
`new-ticket`'s SKILL.md (dotfiles `harness/skills/new-ticket/SKILL.md` §"Priority
by signal") — same bitácora project, same scale, restated here so a kubelab
session never has to leave this repo to know the rule.

Match the **highest** signal that fires:

| Signal in the title/body | Priority |
|---|---|
| Broken or blocking **now** — CI red, a shipped command/tool erroring, secret/data-loss risk, or it blocks other in-flight work | `P0` (rare — reserve for true "stop and fix") |
| A real **defect** in shipped code (`BUG-*`, "fails/errors/wrong"), OR work that **unblocks the active arc** / is the named next step, OR a **security/secrets** gap | `P1` |
| Normal backlog — a capability, refactor, doc, or chore with **no urgency signal** | `P2` (default) |
| Nice-to-have, speculative, **parked/undecided**, cosmetic/polish, or an `IDEAS`/`RFD` research item | `P3` |

When two signals tie, take the higher only if there is a concrete urgency cue
(a date, a blocked dependency, a red CI); absent that, prefer `P2`. Calibrate
against the live distribution before a bulk pass rather than assigning cold —
measured 2026-08-25 on 497 open issues: `P2` 339, empty 136, `P1` 13, `P3` 9,
`P0` 0.

`toolkit board priority --check` (mirrors `board-streams-check`) exits 1 while
any open issue carries no Priority. Not wired into CI, same reasoning as
`board-streams-check` and `board-ids-check`: parallel sessions create issues
faster than a gate could keep up with.
