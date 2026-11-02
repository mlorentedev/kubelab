"""SEC-032 (#2242): the OIDC signing key has one store, SOPS.

A gitignored `infra/config/secrets/{env}.oidc-jwks.pem` used to sit beside it,
written once by `toolkit secrets jwks` and reconciled by nothing. Measured on
msi: every env's pem held a different key from SOPS, and SOPS is what K8s
Authelia serves. These tests keep a second copy from coming back.

Coverage (#2254): every file git tracks under the Makefile, `toolkit/` and
`infra/`, whatever its suffix, and never gitignored output. In each, a path
ending `oidc-jwks.pem` other than the in-container one, the old
`JWKS_FILE_TEMPLATE`, and any read of the key by name outside `KEY_CONSUMERS`.
Not covered: a reader that assembles the name from pieces, and files outside
those roots.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from toolkit.features.secrets_manager import SECRET_CATALOG, SecretsManager

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra/stacks/services/security/authelia/compose.base.yml"
TEMPLATE = ROOT / "infra/config/authelia/templates/configuration.yml.j2"
KEY_PATH = next(s.key_path for s in SECRET_CATALOG if s.key_path.endswith(".oidc_jwks_private_key"))
# The toolkit exports every SOPS value to Compose under its flattened name.
ENV_NAME = KEY_PATH.upper().replace(".", "_")


def _template_key_path() -> str:
    """The in-container path the Authelia template reads the key from."""
    paths = re.findall(r'secret "([^"]+oidc-jwks\.pem)"', TEMPLATE.read_text(encoding="utf-8"))
    assert len(paths) == 1, f"expected one key path in {TEMPLATE.name}, found {paths}"
    return paths[0]


class TestTheDevStackReadsSops:
    def test_no_host_file_is_mounted(self) -> None:
        volumes = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["authelia"].get("volumes", [])
        assert not [v for v in volumes if "oidc-jwks" in str(v)], "the key must not come from a host file"

    def test_the_key_is_a_secret_sourced_from_the_sops_variable(self) -> None:
        compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        mounts = [m for m in compose["services"]["authelia"].get("secrets", []) if isinstance(m, dict)]
        target = _template_key_path()
        sources = [m["source"] for m in mounts if m.get("target") == target]
        assert sources, f"no secret is mounted at {target}, the path the template reads"
        assert compose["secrets"][sources[0]] == {"environment": ENV_NAME}


def test_generating_a_key_writes_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[str, str] = {}

    class _Config:
        def update_secret_key(self, path: str, value: str) -> bool:
            stored[path] = value
            return True

    class _Credentials:
        def generate_jwks_rsa_key(self, _size: int) -> str:
            return "not-a-real-key"

    manager = SecretsManager(tmp_path)
    monkeypatch.setattr(manager, "_cm", lambda env: _Config())
    monkeypatch.setattr(manager, "_credentials_manager", lambda: _Credentials())

    assert manager.generate_jwks("dev") == "not-a-real-key"
    assert stored == {KEY_PATH: "not-a-real-key"}
    assert not [p for p in tmp_path.rglob("*") if p.is_file()], "SOPS is the only store"


# Every tracked file that names the key, under either spelling, and why. A new
# reader has to be added here, which is where a second store in a NEW file would
# be noticed whatever file name it writes (#2254): the literal `oidc-jwks.pem`
# check below cannot see a writer to `signing.pem`. A differently named write
# inside a declared consumer is not caught by name; for `secrets jwks` the test
# above pins that SOPS is its only store.
KEY_CONSUMERS = {
    "infra/config/secrets/dev.enc.yaml": "the store",
    "infra/config/secrets/staging.enc.yaml": "the store",
    "infra/config/secrets/prod.enc.yaml": "the store",
    "infra/stacks/services/security/authelia/compose.base.yml": "dev Authelia, as a Compose secret from the env",
    "toolkit/features/k8s_secrets.py": "K8s Authelia, as a Secret key",
    "toolkit/features/secrets_manager.py": "the catalog entry and `secrets jwks`, which writes SOPS only",
}
KEY_NAMES = (KEY_PATH.rsplit(".", 1)[1], ENV_NAME)
GUARD_ROOTS = ("Makefile", "toolkit", "infra")


def _tracked_texts() -> list[tuple[str, str]]:
    """Every file git tracks under the guard's roots, whatever its suffix, as text.

    Tracked, not walked: gitignored generated output depends on what ran on this
    machine, so reading it would make the verdict depend on the machine. Binary
    files (a NUL byte) carry no path anyone reads.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *GUARD_ROOTS], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    texts = []
    for rel in filter(None, listed.split("\0")):
        data = (ROOT / rel).read_bytes()
        if b"\0" not in data:
            texts.append((rel, data.decode(errors="ignore")))
    return texts


def _offenders(rel: str, text: str) -> list[str]:
    """Why `text`, the content of tracked file `rel`, could be a second store of the key."""
    allowed = _template_key_path()
    found = []
    if "JWKS_FILE_TEMPLATE" in text:
        found.append(f"{rel}: JWKS_FILE_TEMPLATE")
    for match in re.finditer(r"\S*oidc-jwks\.pem", text):
        if match.group(0).strip("'\"") != allowed:
            found.append(f"{rel}: {match.group(0)}")
    if rel not in KEY_CONSUMERS and any(name in text for name in KEY_NAMES):
        found.append(f"{rel}: reads the key by name and is not a declared consumer")
    return found


def test_the_guard_reads_every_tracked_text_file_and_no_generated_one() -> None:
    # Planted, so the "never generated output" half is measured on every machine,
    # a fresh CI clone included, where the generated directory does not exist.
    planted = ROOT / "infra/config/authelia/generated/_guard_probe.yml"
    created = [d for d in planted.parents if not d.exists()]
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(f"{ENV_NAME}: planted\n", encoding="utf-8")
    try:
        rels = {rel for rel, _ in _tracked_texts()}
    finally:
        planted.unlink()
        for directory in created:  # innermost first, as `parents` yields them
            directory.rmdir()
    assert str(planted.relative_to(ROOT)) not in rels, "the guard read gitignored output"
    # Against git's own listing, not a sample: every tracked file it skips must be binary.
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "--", *GUARD_ROOTS], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split("\n")
    ) - {""}
    # The suffix whitelist this guard used to apply (#2254). Reading past it is the point.
    old_suffixes = {".py", ".yml", ".yaml", ".j2", ".sh", ".mk"}
    assert {Path(rel).suffix for rel in rels} - old_suffixes, "the guard reads only the old suffixes"
    skipped = sorted(rel for rel in tracked - rels if b"\0" not in (ROOT / rel).read_bytes())
    assert not skipped, f"tracked text files the guard does not read: {skipped[:10]}"
    assert set(KEY_CONSUMERS) <= rels, f"declared consumers that are not tracked: {set(KEY_CONSUMERS) - rels}"


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("toolkit/_probe.toml", 'jwks = "infra/config/secrets/prod.oidc-jwks.pem"'),
        ("infra/stacks/_probe/Dockerfile", "COPY oidc-jwks.pem /config/"),
        ("toolkit/_probe.py", "JWKS_FILE_TEMPLATE = '{env}.pem'"),
        ("toolkit/_probe.sh", f'printf %s "${ENV_NAME}" > ~/signing.pem'),
        ("toolkit/_probe.py", "value = secrets['oidc_jwks_private_key']"),
    ],
    ids=["toml-path", "dockerfile-path", "template-constant", "env-to-other-file", "key-path-read"],
)
def test_a_planted_second_store_is_caught_in_any_file(rel: str, text: str) -> None:
    assert _offenders(rel, text)


def test_nothing_reads_or_writes_a_host_copy() -> None:
    """Only the in-container path may name the file, and only declared consumers the key."""
    offenders = [line for rel, text in _tracked_texts() for line in _offenders(rel, text)]
    assert not offenders, offenders
