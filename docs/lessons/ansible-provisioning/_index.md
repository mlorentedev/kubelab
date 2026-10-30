# Ansible roles and node provisioning

Newest first. Back to [all categories](../_index.md).

| # | Lesson | Date |
|---|---|---|
| 664 | [A budget that fails the play mid-role drops the handlers notified before it; skip the step when nothing after it needs it](lesson-664-a-budget-that-fails-mid-role-drops-the-handlers-before-it.md) | 2026-10-29 |
| 661 | [A dry run reads the file the previous run rendered, not the one this run would write](lesson-661-a-dry-run-reads-the-file-the-previous-run-rendered.md) | 2026-10-29 |
| 660 | [An address check says where a run lands, not the path its packets take](lesson-660-an-address-check-says-where-a-run-lands-not-the-path-its-packets-take.md) | 2026-10-29 |
| 658 | [Interpreter discovery takes the SSH user's PATH, so a dev-tool shim runs every module as root](lesson-658-interpreter-discovery-follows-the-ssh-users-path.md) | 2026-10-29 |
| 654 | [A file two roles agree on is still rewritten by a writer outside Ansible](lesson-654-a-file-two-roles-agree-on-is-still-rewritten-by-a-writer-outside-ansible.md) | 2026-10-29 |
| 652 | [A guard inside a role refuses after the roles before it changed the host](lesson-652-a-guard-inside-a-role-refuses-after-the-roles-before-it-changed-the-host.md) | 2026-10-29 |
| 645 | [A hold scoped to the maintenance timer leaves every provision free to upgrade](lesson-645-a-hold-scoped-to-the-maintenance-timer-leaves-every-provision-free-to-upgrade.md) | 2026-10-28 |
| 642 | [A version floor in `requirements.yml` never upgrades a controller](lesson-642-a-version-floor-never-upgrades-a-controller.md) | 2026-10-28 |
| 640 | [A guard that pairs two roles by tag says nothing about which runs first](lesson-640-a-guard-that-pairs-two-roles-by-tag-says-nothing-about-which-runs-first.md) | 2026-10-27 |
| 638 | [A guard scoped to one stack leaves its defect open in every other role](lesson-638-a-guard-scoped-to-one-stack-leaves-its-defect-open-in-every-other-role.md) | 2026-10-27 |
| 637 | [A dry run creates no directory, so the next task writing into it fails the check](lesson-637-a-dry-run-creates-no-directory-so-the-next-task-writing-into-it-fails-the-check.md) | 2026-10-27 |
| 636 | [A flag that removes a node must reach every list of nodes, the hand-kept one included](lesson-636-a-flag-that-removes-a-node-must-reach-every-list-of-nodes-including-the-hand-kept-one.md) | 2026-10-27 |
| 630 | [Purging a package removes its unit files but not their failed state, so `systemctl --failed` keeps listing them](lesson-630-purging-a-package-removes-its-unit-files-but-not-their-failed-state.md) | 2026-10-26 |
| 629 | [A flag only `tailscale up` applies drifts unseen while the node stays on the mesh](lesson-629-a-flag-only-tailscale-up-applies-drifts-unseen-while-the-node-stays-on-the-mesh.md) | 2026-10-26 |
| 623 | [A var one play gives a shared role lasts only until the next play that applies the role to the same host](lesson-623-a-var-one-play-gives-a-shared-role-lasts-until-the-next-play-that-applies-it.md) | 2026-10-25 |
| 622 | [A kernel parameter one node must lose can be another node's Wi-Fi country](lesson-622-a-kernel-parameter-one-node-must-lose-can-be-another-nodes-wi-fi-country.md) | 2026-10-25 |
| 620 | [A deferred handler is lost when a later role fails, and the re-run reports changed=0](lesson-620-a-deferred-handler-is-lost-when-a-later-role-fails.md) | 2026-10-25 |
| 604 | [A provision applies the checkout, so a branch behind master rolls the node back without failing](lesson-604-a-provision-applies-the-checkout-so-a-branch-behind-master-rolls-the-node-back-without-failing.md) | 2026-10-17 |
| 589 | [A file written by a subuid with mkstemp is unreadable to its host owner, and no ACL fixes it](lesson-589-a-file-written-by-a-subuid-with-mkstemp-is-unreadable-to-its-host-owner-and-no-acl-fixes-it.md) | 2026-10-17 |
| 588 | [A guard keyed on an error string breaks when the role itself changes what produced the string](lesson-588-a-guard-keyed-on-an-error-string-breaks-when-the-role-changes-what-produced-it.md) | 2026-10-17 |
| 583 | [A mount test that asserts the template passes a path the consumer never sees](lesson-583-a-mount-test-that-asserts-the-template-passes-a-path-the-consumer-never-sees.md) | 2026-10-16 |
| 569 | [A host-key test through a live ControlMaster socket checks nothing](lesson-569-a-host-key-test-through-a-live-controlmaster-socket-checks-nothing.md) | 2026-10-14 |
| 552 | [A kill switch that removes a uid-scoped rule leaves every other unit of that uid unconfined](lesson-552-a-kill-switch-that-removes-a-uid-scoped-rule-leaves-every-other-unit-of-that-uid-unconfined.md) | 2026-10-10 |
| 534 | [A template test that renders without `trim_blocks` is not testing what Ansible ships](lesson-534-a-template-test-that-renders-without-trim-blocks-is-not-testing-what-ansible-ships.md) | 2026-10-07 |
| 530 | [An ignore rule for Ansible Vault files swallows a task file named `vault.yml`](lesson-530-an-ignore-rule-for-ansible-vault-files-swallows-a-task-file-named-vault-yml.md) | 2026-10-07 |
| 519 | [A remote `~` is the home of whoever runs the task, so a role that uses one has a result per caller](lesson-519-a-remote-tilde-is-the-home-of-whoever-runs-the-task.md) | 2026-10-04 |
| 506 | [A health check against `localhost` fails once the port binds to the tailnet, and only on the first provision after](lesson-506-a-health-check-against-localhost-fails-once-the-port-binds-to-the-tailnet.md) | 2026-10-02 |
| 497 | [A folded YAML scalar keeps `'\n'` as two characters, so a guard built on it can loop over nothing](lesson-497-a-folded-yaml-scalar-keeps-backslash-n-so-a-guard-can-loop-over-nothing.md) | 2026-10-01 |
| 496 | [`changed_when: false` does not make a task a read](lesson-496-changed-when-false-does-not-make-a-task-a-read.md) | 2026-10-01 |
| 493 | [Three convergence bugs in one role each looked like a different symptom, and the recap showed none of them](lesson-493-a-role-that-fails-after-its-first-success-hides-behind-the-recap.md) | 2026-10-01 |
| 466 | [A "back up the current file" task before a template reports `changed` on the run after every change](lesson-466-a-backup-copy-before-a-template-reports-changed-on-the-next-run.md) | 2026-09-26 |
| 397 | [Check mode skips `command:`, so every condition reading its register fails the dry run](lesson-397-check-mode-skips-command-so-every-condition-reading-its-register-fails-the-dry-run.md) | 2026-08-26 |
| 392 | [`--check` skips `command:`, so a guard reading its rc does not gate](lesson-392-check-mode-skips-command-so-a-guard-reading-its-rc-does-not-gate.md) | 2026-08-24 |
| 381 | [Handlers chain only by explicit notify, and only forward](lesson-381-handlers-chain-only-by-explicit-notify-and-only-forward.md) | 2026-08-23 |
| 367 | [A task that acquires state must survive the task that uses it](lesson-367-a-task-that-acquires-state-must-survive-the-task-that-uses-it.md) | 2026-08-22 |
| 360 | [A shell creates the redirect target before it resolves the command](lesson-360-a-shell-creates-the-redirect-target-before-it-resolves-the-command.md) | 2026-08-21 |
| 356 | [An Ansible play whose `hosts:` pattern matches nothing succeeds](lesson-356-unmatched-host-pattern-is-a-warning.md) | 2026-08-20 |
| 349 | [Presence is not coverage — a package can be installed on a host nothing manages](lesson-349-presence-is-not-coverage-a-package-can-be-installed-and-unmanaged.md) | 2026-08-18 |
| 337 | [Adding a role to a playbook does not install it on any path that never runs the playbook](lesson-337-adding-a-role-to-a-playbook-does-not-install-.md) | 2026-08-15 |
| 325 | [`--tags` silently skips prerequisite `pre_tasks` that were never tagged, and a shared secret key collides across an Ansible env-override merge](lesson-325-tags-silently-skips-prerequisite-pre-tasks-th.md) | 2026-08-14 |
| 324 | [Ansible's `apt` module can report `changed: true` for two unrelated reasons that both look like "nothing really happened"](lesson-324-ansible-s-apt-module-can-report-changed-true-.md) | 2026-08-14 |
| 006 | [A config that provisions cleanly can still fail at delivery](lesson-006-a-config-that-provisions-cleanly-can-still-fa.md) | 2026-08-10 |
| 300 | [A blocked probe hides every defect downstream of where it stops (ANSIBLE-033)](lesson-300-a-blocked-probe-hides-every-defect-downstream.md) | 2026-08-08 |
| 299 | [A tag asymmetry made the play report success while delivering no credential — and the acceptance probe agreed (ANSIBLE-033)](lesson-299-a-tag-asymmetry-made-the-play-report-success-.md) | 2026-08-08 |
| 298 | [When you cannot own the file, verify it — a guarded write is not a fallback (ANSIBLE-033)](lesson-298-when-you-cannot-own-the-file-verify-it-a-guar.md) | 2026-08-08 |
| 297 | [Two merge implementations over the same files meant `common.enc.yaml` had two different meanings (ANSIBLE-033)](lesson-297-two-merge-implementations-over-the-same-files.md) | 2026-08-08 |
| 296 | [Ansible has no native Windows control node — provision from Linux, and budget for the controller's own toolchain (ANSIBLE-028)](lesson-296-ansible-has-no-native-windows-control-node-pr.md) | 2026-08-07 |
| 295 | [A config file with two writers can never converge — idempotence is a property of the system, not of the task (ANSIBLE-028)](lesson-295-a-config-file-with-two-writers-can-never-conv.md) | 2026-08-07 |
| 260 | [Pre-flight Plays need per-playbook tagging — blanket `tags: [always]` breaks playbooks designed for one-time installs](lesson-260-pre-flight-plays-need-per-playbook-tagging-bl.md) | 2026-05-19 |
| 257 | [Ansible pre_tasks loading SSOT config MUST be tagged `[always]` for tag-selective deploys](lesson-257-ansible-pre-tasks-loading-ssot-config-must-be.md) | 2026-05-19 |
| 255 | [journald SystemMaxUse only vacuums archived journals — active journal can briefly exceed cap](lesson-255-journald-systemmaxuse-only-vacuums-archived-j.md) | 2026-05-12 |
| 254 | [Ubuntu /etc/logrotate.d/rsyslog groups 6 syslog paths into ONE block — regex must match multi-path stanza](lesson-254-ubuntu-etc-logrotate-d-rsyslog-groups-6-syslo.md) | 2026-05-12 |
| 253 | [aws_spot_instance_request silently drops root_block_device updates — migrate to aws_instance + instance_market_options](lesson-253-aws-spot-instance-request-silently-drops-root.md) | 2026-05-11 |
| 252 | [Persistent journald on Debian RPi needs 99- drop-in AND post-restart flush](lesson-252-persistent-journald-on-debian-rpi-needs-99-dr.md) | 2026-05-11 |
| 251 | [Terraform data.aws_ami filter drift triggers Spot replacement on every plan](lesson-251-terraform-data-aws-ami-filter-drift-triggers-.md) | 2026-05-10 |
| 250 | [Rotated syslog files (un-gzipped) consume 200MB+ on busy nodes — maintain role missed it](lesson-250-rotated-syslog-files-un-gzipped-consume-200mb.md) | 2026-05-10 |
| 245 | [Ansible apt module in --check mode reports stale-cache false positives](lesson-245-ansible-apt-module-in-check-mode-reports-stal.md) | 2026-05-10 |
| 244 | [Cloud-init bootstrap without Ansible day-2 path is invisible technical debt](lesson-244-cloud-init-bootstrap-without-ansible-day-2-pa.md) | 2026-05-09 |
| 239 | [2026-03-29: Docker Tailscale-only port binding breaks K8s EndpointSlice + Ansible health checks](lesson-239-2026-03-29-docker-tailscale-only-port-binding.md) | 2026-05-01 |
| 220 | [aws1 t4g.micro disk-pressure blocks all pod scheduling](lesson-220-aws1-t4g-micro-disk-pressure-blocks-all-pod-s.md) | 2026-03-27 |
| 211 | [Spot `stop` behavior causes stale state — use `terminate` for cattle](lesson-211-spot-stop-behavior-causes-stale-state-use-ter.md) | 2026-03-26 |
| 210 | [cloud-init `#cloud-config` must be first line](lesson-210-cloud-init-cloud-config-must-be-first-line.md) | 2026-03-26 |
| 180 | [cloud-init YAML: colons in strings cause parse errors](lesson-180-cloud-init-yaml-colons-in-strings-cause-parse.md) | 2026-03-22 |
| 172 | [deploy-vps must be idempotent — skip Docker Compose Traefik when K3s is active](lesson-172-deploy-vps-must-be-idempotent-skip-docker-com.md) | 2026-03-22 |
| 171 | [Docker containers need explicit DNS on systemd-resolved hosts](lesson-171-docker-containers-need-explicit-dns-on-system.md) | 2026-03-22 |
| 169 | [VPS ansible_host must use public IP — bootstrap circular dependency](lesson-169-vps-ansible-host-must-use-public-ip-bootstrap.md) | 2026-03-22 |
| 159 | [Ansible inventory must be env-aware for k3s_servers group](lesson-159-ansible-inventory-must-be-env-aware-for-k3s-s.md) | 2026-03-22 |
| 037 | [apt_repository on Ubuntu 24.04 generates non-obvious filenames](lesson-037-apt-repository-on-ubuntu-24-04-generates-non-.md) | 2026-03-19 |
| 036 | [Docker GPG key: never delete .asc on re-runs](lesson-036-docker-gpg-key-never-delete-asc-on-re-runs.md) | 2026-03-19 |
| 032 | [deploy-dns.yml must read from common.yaml, not merged config](lesson-032-deploy-dns-yml-must-read-from-common-yaml-not.md) | 2026-03-19 |
| 031 | [Jetson Nano loses IP on DHCP failure — use static nmcli config](lesson-031-jetson-nano-loses-ip-on-dhcp-failure-use-stat.md) | 2026-03-19 |
| 131 | [Tailscale up disrupts SSH during Ansible provisioning](lesson-131-tailscale-up-disrupts-ssh-during-ansible-prov.md) | 2026-03-17 |
| 128 | [Pre-flight SSH validation prevents ssh_hardening lockout](lesson-128-pre-flight-ssh-validation-prevents-ssh-harden.md) | 2026-03-17 |
| 127 | [Ansible role variables: dead code from playbook-side flags](lesson-127-ansible-role-variables-dead-code-from-playboo.md) | 2026-03-17 |
| 112 | [USB ETH RPi4 — router DHCP not responding](lesson-112-usb-eth-rpi4-router-dhcp-not-responding.md) | 2026-03-14 |
| 109 | [RPi4 full SD card reflash — recovery procedure](lesson-109-rpi4-full-sd-card-reflash-recovery-procedure.md) | 2026-03-14 |
| 108 | [RPi4 SD reflash — /etc/hosts VPN fallback missing](lesson-108-rpi4-sd-reflash-etc-hosts-vpn-fallback-missin.md) | 2026-03-14 |
| 097 | [CoreDNS on RPi4 Is Completely Outside K3s and Ansible Automation](lesson-097-coredns-on-rpi4-is-completely-outside-k3s-and.md) | 2026-03-01 |
| 054 | [Proxmox Hostname Rename Breaks VM Visibility](lesson-054-proxmox-hostname-rename-breaks-vm-visibility.md) | 2026-02-20 |
| 049 | [Ansible Templates Drift from Code](lesson-049-ansible-templates-drift-from-code.md) | 2026-02-09 |
