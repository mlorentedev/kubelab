---
id: "lesson-563-a-wrapper-guard-is-only-as-strong-as-the-environment-it-passes-on"
type: lesson
status: active
title: "A wrapper's guard is only as strong as the environment it passes on"
created: "2026-10-13"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, terraform, guard, environment]
---

# A wrapper's guard is only as strong as the environment it passes on

**Context**: TF-007 PR 1a put every Terraform run behind one runner
(`toolkit/features/terraform_runner.py`). A guarded apply saves the plan, reads
it with `terraform show -json`, refuses a delete or replace that was not named,
and then applies that saved file. The child's environment stripped only
`AWS_*` and `TF_VAR_*`, so an inherited value could not outrank the SSOT.

**Problem**: Terraform reads more than variables from its environment.
`TF_CLI_ARGS_apply=-auto-approve` appends arguments to every apply.
`TF_LOG=trace` can write the injected `TF_VAR_` values to stderr or to
`TF_LOG_PATH`. `TF_WORKSPACE` switches the state the plan is read against.
`TF_DATA_DIR` moves `.terraform/` and the backend's cached configuration. A
shell, a CI job or a `.envrc` that sets any of these changes what the guarded
command does, and the wrapper reports nothing. The guard's tests passed
because they never set these variables. The gap was found by review of #2236,
not by a failure.

**Solution**: The runner now strips every `TF_*` except an explicit allowlist
of variables that only change speed (`INHERITED_TF`: the plugin cache). Inputs
reach terraform only from the SSOT. `tests/test_terraform_runner.py::test_no_inherited_tf_variable_changes_what_terraform_does`
sets each dangerous variable and asserts the child never sees it. Replacing the
filter with `or True` turns the test red.

**Rule**: When a wrapper exists to enforce something, its child environment is
an allowlist, never a blocklist. Read the tool's documentation for every
variable family it honours (`TF_*`, `GIT_*`, `KUBECTL_*`, `ANSIBLE_*`). Pass on
only what changes speed or cosmetics, and test that a hostile value is dropped.

**Tags**: `#terraform` `#guard` `#pr-2236`
