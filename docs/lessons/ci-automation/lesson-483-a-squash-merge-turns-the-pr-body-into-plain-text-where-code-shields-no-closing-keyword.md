---
id: lesson-483-a-squash-merge-turns-the-pr-body-into-plain-text-where-code-shields-no-closing-keyword
type: lesson
status: active
created: "2026-09-28"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github, spec-gate]
---

# A squash merge turns the PR body into plain text, where code shields no closing keyword

**Context**: OPS-023 was split into PR 3a (#1880) and PR 3b (#1890), and only 3b was meant to close the spec's issue, #972. 3a's body explained the split in prose: "The docs sweep ... follow in PR 3b, which carries `Closes #972`." The keyword sat inside backticks on purpose. Lesson-348 had measured that `closingIssuesReferences` ignores code spans, and CI-GATE-013 had taught the spec archive gate to strip code for the same reason.

**Problem**: #1880 merged, and #972 closed with it. The spec was still active and 3b was still open. Both checks passed: `closingIssuesReferences` for #1880 returned `[]` and the spec gate was green. The timeline shows what closed the issue:

```bash
gh api repos/mlorentedev/kubelab/issues/972/timeline --paginate \
  --jq '.[] | select(.event=="closed") | "\(.created_at) \(.commit_id)"'
# 2026-09-28T02:38:50Z 30a90cf6ee24e8f8dfdf0edbd7ac5de97c7f8491   <- #1880's squash commit
gh api repos/mlorentedev/kubelab --jq .squash_merge_commit_message
# PR_BODY
```

A PR body passes through two parsers. The PR-link parser reads markdown and skips code. The squash (`PR_BODY`) then copies the body into the commit message, and GitHub reads closing keywords out of commits pushed to the default branch, as plain text with no markdown. A merge closes whatever either parser finds. Lesson-348 measured only the first parser and concluded that code is safe, and the gate inherited the conclusion.

The earlier counter-case does not refute this. #1155's squash commit (`d192d9b8`) closed nothing only because its body had been reworded until no keyword was left next to a number in any form. The raw scan of that commit message finds no match.

**Solution**: #972 was reopened. CI-GATE-019 (#1903) makes `closed_issues()` scan the raw body. The code strip still applies to the `Spec-archive-exception:` waiver, because only the gate reads that line. A test pins #1880's literal line to `{972}`. The CI-GATE-013 cases that expected code to shield a keyword now expect the issue number, and the module's measurement table has a dated row for this result.

**Rule**:

- **Code shields a closing keyword from one of GitHub's two parsers, not from the merge.** With squash `PR_BODY`, whatever the body says, the commit says too. To mention an issue a PR must not close, use `closing #N`, or leave the number out, whatever the formatting.
- **`closingIssuesReferences` tells you what the PR links, not what the merge closes.** The only proof of what a merge closed is the issue timeline afterwards (`closed` with a `commit_id`).
- **A measurement is valid for the parser it was taken against.** Lesson-348 recorded which parser each of its results came from. The gate lost that qualifier and applied the result to the whole merge.

**Tags**: `#github` `#spec-gate` `#squash-merge` `#closing-keywords` `#pr-1880` `#issue-972` `#ci-gate-019`
