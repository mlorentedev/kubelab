# Ansible roles and node provisioning

43 lessons, newest first. Back to [all categories](../_index.md).

| # | Lesson | Date |
|---|---|---|
| 349 | [Presence is not coverage — a package can be installed on a host nothing manages](lesson-349-presence-is-not-coverage-a-package-can-be-installed-and-unmanaged.md) | 2026-08-18 |
| 337 | [Adding a role to a playbook does not install it on any path that never runs the playbook](lesson-337-adding-a-role-to-a-playbook-does-not-install-.md) | 2026-08-15 |
| 325 | [`--tags` silently skips prerequisite `pre_tasks` that were never tagged, and a shared secret key collides across an Ansible env-override merge](lesson-325-tags-silently-skips-prerequisite-pre-tasks-th.md) | 2026-08-14 |
| 324 | [Ansible's `apt` module can report `changed: true` for two unrelated reasons that both look like "nothing really happened"](lesson-324-ansible-s-apt-module-can-report-changed-true-.md) | 2026-08-14 |
| 006 | [A config that provisions cleanly can still fail at delivery](lesson-006-a-config-that-provisions-cleanly-can-still-fa.md) | 2026-08-10 |
| 298 | [When you cannot own the file, verify it — a guarded write is not a fallback (ANSIBLE-033)](lesson-298-when-you-cannot-own-the-file-verify-it-a-guar.md) | 2026-08-08 |
| 300 | [A blocked probe hides every defect downstream of where it stops (ANSIBLE-033)](lesson-300-a-blocked-probe-hides-every-defect-downstream.md) | 2026-08-08 |
| 299 | [A tag asymmetry made the play report success while delivering no credential — and the acceptance probe agreed (ANSIBLE-033)](lesson-299-a-tag-asymmetry-made-the-play-report-success-.md) | 2026-08-08 |
| 297 | [Two merge implementations over the same files meant `common.enc.yaml` had two different meanings (ANSIBLE-033)](lesson-297-two-merge-implementations-over-the-same-files.md) | 2026-08-08 |
| 296 | [Ansible has no native Windows control node — provision from Linux, and budget for the controller's own toolchain (ANSIBLE-028)](lesson-296-ansible-has-no-native-windows-control-node-pr.md) | 2026-08-07 |
| 295 | [A config file with two writers can never converge — idempotence is a property of the system, not of the task (ANSIBLE-028)](lesson-295-a-config-file-with-two-writers-can-never-conv.md) | 2026-08-07 |
| 257 | [Ansible pre_tasks loading SSOT config MUST be tagged `[always]` for tag-selective deploys](lesson-257-ansible-pre-tasks-loading-ssot-config-must-be.md) | 2026-05-19 |
| 260 | [Pre-flight Plays need per-playbook tagging — blanket `tags: [always]` breaks playbooks designed for one-time installs](lesson-260-pre-flight-plays-need-per-playbook-tagging-bl.md) | 2026-05-19 |
| 254 | [Ubuntu /etc/logrotate.d/rsyslog groups 6 syslog paths into ONE block — regex must match multi-path stanza](lesson-254-ubuntu-etc-logrotate-d-rsyslog-groups-6-syslo.md) | 2026-05-12 |
| 255 | [journald SystemMaxUse only vacuums archived journals — active journal can briefly exceed cap](lesson-255-journald-systemmaxuse-only-vacuums-archived-j.md) | 2026-05-12 |
| 253 | [aws_spot_instance_request silently drops root_block_device updates — migrate to aws_instance + instance_market_options](lesson-253-aws-spot-instance-request-silently-drops-root.md) | 2026-05-11 |
| 252 | [Persistent journald on Debian RPi needs 99- drop-in AND post-restart flush](lesson-252-persistent-journald-on-debian-rpi-needs-99-dr.md) | 2026-05-11 |
| 245 | [Ansible apt module in --check mode reports stale-cache false positives](lesson-245-ansible-apt-module-in-check-mode-reports-stal.md) | 2026-05-10 |
| 251 | [Terraform data.aws_ami filter drift triggers Spot replacement on every plan](lesson-251-terraform-data-aws-ami-filter-drift-triggers-.md) | 2026-05-10 |
| 250 | [Rotated syslog files (un-gzipped) consume 200MB+ on busy nodes — maintain role missed it](lesson-250-rotated-syslog-files-un-gzipped-consume-200mb.md) | 2026-05-10 |
| 244 | [Cloud-init bootstrap without Ansible day-2 path is invisible technical debt](lesson-244-cloud-init-bootstrap-without-ansible-day-2-pa.md) | 2026-05-09 |
| 239 | [2026-03-29: Docker Tailscale-only port binding breaks K8s EndpointSlice + Ansible health checks](lesson-239-2026-03-29-docker-tailscale-only-port-binding.md) | 2026-05-01 |
| 220 | [aws1 t4g.micro disk-pressure blocks all pod scheduling](lesson-220-aws1-t4g-micro-disk-pressure-blocks-all-pod-s.md) | 2026-03-27 |
| 211 | [Spot `stop` behavior causes stale state — use `terminate` for cattle](lesson-211-spot-stop-behavior-causes-stale-state-use-ter.md) | 2026-03-26 |
| 210 | [cloud-init `#cloud-config` must be first line](lesson-210-cloud-init-cloud-config-must-be-first-line.md) | 2026-03-26 |
| 159 | [Ansible inventory must be env-aware for k3s_servers group](lesson-159-ansible-inventory-must-be-env-aware-for-k3s-s.md) | 2026-03-22 |
| 180 | [cloud-init YAML: colons in strings cause parse errors](lesson-180-cloud-init-yaml-colons-in-strings-cause-parse.md) | 2026-03-22 |
| 169 | [VPS ansible_host must use public IP — bootstrap circular dependency](lesson-169-vps-ansible-host-must-use-public-ip-bootstrap.md) | 2026-03-22 |
| 171 | [Docker containers need explicit DNS on systemd-resolved hosts](lesson-171-docker-containers-need-explicit-dns-on-system.md) | 2026-03-22 |
| 172 | [deploy-vps must be idempotent — skip Docker Compose Traefik when K3s is active](lesson-172-deploy-vps-must-be-idempotent-skip-docker-com.md) | 2026-03-22 |
| 036 | [Docker GPG key: never delete .asc on re-runs](lesson-036-docker-gpg-key-never-delete-asc-on-re-runs.md) | 2026-03-19 |
| 037 | [apt_repository on Ubuntu 24.04 generates non-obvious filenames](lesson-037-apt-repository-on-ubuntu-24-04-generates-non-.md) | 2026-03-19 |
| 032 | [deploy-dns.yml must read from common.yaml, not merged config](lesson-032-deploy-dns-yml-must-read-from-common-yaml-not.md) | 2026-03-19 |
| 031 | [Jetson Nano loses IP on DHCP failure — use static nmcli config](lesson-031-jetson-nano-loses-ip-on-dhcp-failure-use-stat.md) | 2026-03-19 |
| 131 | [Tailscale up disrupts SSH during Ansible provisioning](lesson-131-tailscale-up-disrupts-ssh-during-ansible-prov.md) | 2026-03-17 |
| 128 | [Pre-flight SSH validation prevents ssh_hardening lockout](lesson-128-pre-flight-ssh-validation-prevents-ssh-harden.md) | 2026-03-17 |
| 127 | [Ansible role variables: dead code from playbook-side flags](lesson-127-ansible-role-variables-dead-code-from-playboo.md) | 2026-03-17 |
| 108 | [RPi4 SD reflash — /etc/hosts VPN fallback missing](lesson-108-rpi4-sd-reflash-etc-hosts-vpn-fallback-missin.md) | 2026-03-14 |
| 109 | [RPi4 full SD card reflash — recovery procedure](lesson-109-rpi4-full-sd-card-reflash-recovery-procedure.md) | 2026-03-14 |
| 112 | [USB ETH RPi4 — router DHCP not responding](lesson-112-usb-eth-rpi4-router-dhcp-not-responding.md) | 2026-03-14 |
| 097 | [CoreDNS on RPi4 Is Completely Outside K3s and Ansible Automation](lesson-097-coredns-on-rpi4-is-completely-outside-k3s-and.md) | 2026-03-01 |
| 054 | [Proxmox Hostname Rename Breaks VM Visibility](lesson-054-proxmox-hostname-rename-breaks-vm-visibility.md) | 2026-02-20 |
| 049 | [Ansible Templates Drift from Code](lesson-049-ansible-templates-drift-from-code.md) | 2026-02-09 |
