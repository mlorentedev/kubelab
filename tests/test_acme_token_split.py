"""No node receives the Terraform DNS token (#2459).

Traefik's ACME DNS-01 resolver needs `Zone:DNS:Edit` on the zones it issues
for, nothing more. `cloudflare.api_token` is Terraform's credential: it edits
records and zone settings on every zone. Before the split both resolvers read
it, so whoever read the in-cluster `cloudflare-api-token` Secret could take over
DNS for every managed zone. Each variable that carries a token to Traefik must
name the ACME key, and no Ansible file may name the Terraform one at all.
"""

from __future__ import annotations

import pathlib
import re

from toolkit.features import secrets_manager, terraform_runner

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE = REPO_ROOT / "infra/ansible"

ACME_KEY = "cloudflare.acme_dns_token"
TERRAFORM_KEY = "cloudflare.api_token"

#: The two variables that carry a Cloudflare token to Traefik: the K3s
#: HelmChartConfig Secret, and the VPS Docker Compose Traefik.
ACME_VARS = ("k3s_traefik_acme_cloudflare_token", "traefik_cf_dns_api_token")


def _ansible_files() -> list[pathlib.Path]:
    return sorted(p for ext in ("*.yml", "*.yaml", "*.j2") for p in ANSIBLE.rglob(ext))


def test_every_acme_variable_reads_the_acme_key() -> None:
    assignments = []
    for path in _ansible_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(rf"\s*({'|'.join(ACME_VARS)}):\s*(.+)", line)
            if match and "{{" in match.group(2):
                assignments.append((path.relative_to(REPO_ROOT), match.group(2)))
    # Four today: provision-vps and provision-ace1 (K3s), deploy-vps and
    # provision-vps (Compose). Pinning the floor keeps a rename from passing empty.
    assert len(assignments) >= 4, assignments
    wrong = [(str(p), v) for p, v in assignments if ACME_KEY not in v]
    assert not wrong, f"these ACME token variables do not read {ACME_KEY}: {wrong}"


def test_no_ansible_file_names_the_terraform_token() -> None:
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _ansible_files()
        if re.search(r"cloudflare\.api_token\b", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"{TERRAFORM_KEY} is Terraform's credential and must reach no node: {offenders}"


def test_the_catalog_separates_the_two_tokens() -> None:
    specs = {s.key_path: s for s in secrets_manager.SECRET_CATALOG}
    assert specs[ACME_KEY].services == ("traefik",)
    assert specs[TERRAFORM_KEY].services == ("terraform",)
    assert terraform_runner.ROOTS["dns"].secrets == {"cloudflare_api_token": TERRAFORM_KEY}
