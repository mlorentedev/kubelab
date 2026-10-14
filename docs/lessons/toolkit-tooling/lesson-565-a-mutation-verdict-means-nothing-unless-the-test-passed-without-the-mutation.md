---
id: lesson-565-a-mutation-verdict-means-nothing-unless-the-test-passed-without-the-mutation
type: lesson
status: active
created: "2026-10-13"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, mutation-testing, pytest, baseline]
---

# A mutation verdict means nothing unless the test passed without the mutation

**Context**: Mutation-testing `tests/test_terraform_runner.py` with `make mutate`
for TF-007. The file held two tests that were red on purpose, written ahead of
the code they cover.

**Problem**: Every mutant reported RED, including one that a correct baseline
showed GREEN. `mutate.run` applied the mutation, ran the test and treated pytest
exit 1 as "the guard caught it". It never asked whether the same test passed
before the mutation. A target that is already failing exits 1 against every
mutant, whatever the mutant did, so each verdict certified a guard that was never
shown to work. The tool existed to produce evidence and produced the opposite
without a sign of it: the output read `RED: the test failed against the mutant`.

**Solution**: `mutate.run` runs the test once against the unmutated file, after
the cheap refusals (dirty tree, no unique match) and before the first byte is
written. Anything but exit 0 raises `Refused` (exit 2, nothing mutated), naming
the exit code and saying how to get a usable baseline: deselect the unrelated
failures, for example `TEST='tests/x.py -k <passing tests>'`. A baseline that
does not run to a verdict (collection error, nothing collected) is refused the
same way. The cost is one extra pytest run per mutation.
`tests/test_mutate.py::test_a_test_that_does_not_pass_without_the_mutation_refuses`
asserts that the test ran once, against the original, and left the file
untouched; `test_a_failing_test_target_refuses_through_the_command` does it
end to end with the real pytest. Dropping the check with `make mutate` turned 15
of those tests red.

**Rule**: A result that is a comparison needs both sides measured. Before
reporting that a change broke a test, show that the test passed without the
change. The same holds for any "it went red" evidence: a red that was already
there is not a catch.

**Tags**: `#mutation-testing` `#pytest` `#baseline` `#tool-100`
