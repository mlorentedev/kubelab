# TOOL-078 tasks

- [x] T1: failing tests for the rules (repository shape, head vs base, title) and for the client calls
      (endpoint, payload, basic auth, no token header).
- [x] T2: `create_pull` / `create_issue` on `GiteaBasicAuthClient`.
- [x] T3: `toolkit/features/gitea_authoring.py`: payload rules and the client built from the push credential.
- [x] T4: `toolkit services gitea pr create` / `issue create`, with a CLI test that the password never
      reaches output.
- [ ] T5: live: open the `fix/onboarding-figure` PR and the worktree-defect issue on `personal/resume`.
- [ ] T6: replace "Manu opens the PR in the web UI" in `resume`'s memory with the command.
