---
id: lesson-283-make-fetch-kubeconfig-from-a-non-admin-window
type: lesson
status: active
created: "2026-06-22"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# `make fetch-kubeconfig` from a non-admin Windows box fails silently from PowerShell — ssh-agent in Git Bash is mandatory

**Context:** TOOL-015 live smoke from EGW-LEN029 (corporate non-admin Windows, no native Tailscale). The toolkit's `fetch-kubeconfig` command auto-falls back to a transient ts-bridge SSH tunnel when the direct alias (mesh IP) is unreachable. First run was from PowerShell; it printed "Connection closed by 127.0.0.1 port N" and exited non-zero. The tunnel was up (ts-bridge had registered on Headscale); the failure was not a connectivity problem.

**Problem:** `make fetch-kubeconfig` in PowerShell invokes `ssh` with a passphrase-protected key. On a non-admin Windows box, the `ssh-agent` Windows Service is **Disabled** (enabling it requires admin). Without an agent, `ssh` must prompt for the passphrase interactively. But `fetch_kubeconfig` wraps the SSH call in `subprocess.run(capture_output=True)` — stdout and stderr are redirected, and the passphrase prompt never reaches the terminal. The user sees nothing; `ssh` sees a blank passphrase; the server sends "Connection closed" (not "Permission denied"), which is a connect-failure pattern and triggers the tunnel fallback, which also fails for the same reason. Neither error message points at passphrase auth as the root cause. Identical symptom could be confused with ts-bridge not routing correctly (wrong target, bad key, firewall), wasting diagnostic time.

**Solution:** Run `make fetch-kubeconfig` (and all kubelab SSH-based toolkit commands) from **Git Bash**, not PowerShell. Git Bash ships its own OpenSSH and `ssh-agent`. Load the agent once per shell session before the first toolkit call:

```bash
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519   # one passphrase prompt
make fetch-kubeconfig ENV=staging
```

The agent stays alive for the shell session, so `make connect` + `kubectl get ns` can follow immediately without a re-prompt. **PowerShell works only if** the Windows SSH Agent service is enabled (requires admin) and the key is added to it. The Git Bash agent does NOT propagate to PowerShell (they are separate processes), and vice versa.

**Diagnostic tell:** `_is_connect_failure(255, "Connection closed by 127.0.0.1 ...")` returns True (exit 255 + connect-error substring), so the fallback fires again, masking the auth root cause. If the tunnel fetch ALSO closes the connection, suspect passphrase/agent before suspect ts-bridge routing. Confirm with `ssh -v -p <tunnel_port> <user>@127.0.0.1` — it will show "Authentications that can continue: publickey" and then "Disconnected: No supported authentication methods available (server sent: publickey)" when the agent is missing.

**Tags:** `#windows` `#ssh` `#ssh-agent` `#non-admin` `#fetch-kubeconfig` `#ts-bridge` `#tool-015` `#gotcha`
