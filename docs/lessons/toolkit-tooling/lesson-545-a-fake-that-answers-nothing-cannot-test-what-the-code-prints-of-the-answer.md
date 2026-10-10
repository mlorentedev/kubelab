---
id: lesson-545-a-fake-that-answers-nothing-cannot-test-what-the-code-prints-of-the-answer
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, secrets, n8n]
---

# A fake that answers nothing cannot test what the code prints of the answer

**Context**: The n8n importer pipes each credential payload into the pod on stdin, and APP-CONFIG-018 pinned that no secret reaches the terminal with `test_nothing_secret_reaches_the_output`. The spec's adversarial review asked whether that test could see the importer's own `_run`, which logs the pod's stdout on success and its stderr on failure.

**Problem**: It could not. The fake `kubectl` returned `stdout=""` for every exec, so the code path that prints what the pod answered never had anything to print, and the test passed whatever that path did. Given a fake that repeats its input, as a CLI reporting a parse error might, the same suite went red on all three paths (success, failed credential import, failed workflow import): every SOPS value in the payload reached the terminal. A second trap sat behind the first: echoed raw, a value appears JSON-escaped, so masking only the decoded strings still let the site tag through inside a GraphQL query.

**Solution**: `_run` masks what the pod prints against the payload it was fed, every string value of six characters or more in both its decoded and its JSON-escaped form (`_mask_payload` in `toolkit/features/n8n_import.py`). The fake gained `echo=True`, and `test_a_cli_that_repeats_its_input_does_not_put_a_secret_on_the_terminal` runs the three paths through it. `make mutate` killed four mutants: no masking on stdout, none on stderr, no escaped form, and the schedule pin added alongside.

**Rule**: A no-leak test is only as strong as the most talkative thing its fake would say. When code logs what a dependency returns, the fake must return something that contains the secret, or the test asserts nothing about that path. Same shape as openkm-brain#40, where a fake converter that emitted no headings hid a parser that never matched one.

**Tags**: `#testing` `#secrets` `#n8n` `#app-config-018`
