---
id: lesson-675-a-probe-read-before-the-declaration-fails-an-env-on-another-envs-outage
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, e2e, testing]
---

# A probe read before the declaration fails an env on another env's outage

**Context**: The e2e suite decides to skip a service in two steps. A service can declare envs it never runs in (`skip_in_envs`), and a service on an on-demand node gets a TCP probe of that node, which skips on silence and fails on a refusal (lesson-631). Open WebUI runs only in prod, so it declares `("dev", "staging")`, and its backend is ace2.

**Problem**: `make test-e2e ENV=staging` failed twice on Open WebUI, a service staging does not run: `test_security_headers_present[open_webui]` and `test_hsts_header[open_webui]`, both `ConnectionRefusedError` on ace2's `100.64.0.5:3080` while ace2's image store was empty (#2703). Those two tests probed the backend before they read the declaration, and every other caller read them the other way round. Each caller ordered the two steps itself, so the order was a convention five places deep, and one of them had it backwards. The same run passed once ace2 answered, so the failure looked like ace2's state rather than a test defect, and was first recorded as a homelab problem.

**Solution**: `skip_reason(svc_name, exp, env)` in `tests/e2e/expectations.py` reads the declaration and only then delegates to `on_demand_skip_reason`. Every e2e caller now goes through it. `tests/test_e2e_skip_reason_wording.py` drives each caller with a refusing loopback port in an env the service declares away and expects a skip, and fails if any `tests/e2e/test_*.py` calls the probe directly.

**Rule**: When two checks must run in a fixed order, put the order in one function and make the callers use it. A rule each caller restates holds only until one caller restates it wrong. A test result that changes with the state of a node the env never targets is a test defect until shown otherwise.

**Tags**: `#e2e` `#testing` `#single-source`
