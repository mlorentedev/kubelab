"""SSOT-015 (#1543): a `config.*` key an Ansible playbook reads must exist.

Ansible and the toolkit consume the same values files by different routes, and
only one of them runs the derivations:

    toolkit (generators, k8s, secrets, health)  ->  ConfigLoader   -> sees them
    Ansible playbooks                           ->  include_vars   -> does NOT

`ConfigLoader._inject_contact_email_derivations` (SSOT-014c) fills four fields
from `apps.contact.email`, of which `edge.traefik.acme_email` is one. It is
therefore absent from every values file on purpose, and `common.yaml` says so in
a comment -- which is not a mechanism. On 2026-09-02 `make deploy TARGET=k3s`
died on it:

    object of type 'dict' has no attribute 'acme_email'
    deploy-k3s.yml:77 -> config.edge.traefik.acme_email

The consequence is the part worth remembering: the Traefik HelmChartConfig had
not been reproducible from the repo through its documented path for as long as
that was true, and nothing said so. This failure is invisible in CI (no playbook
runs there) and invisible to `make validate` and `make test` (both read through
the toolkit, where the key is present). It surfaces only at deploy time.

Auditing the rest afterwards found three more references to the same key and one
to `observability.loki.domain`, which #1530 had deleted from prod.yaml. All four
were latent rather than live -- their roles are skipped in prod -- which is
precisely why nobody noticed.

WHAT THIS ASSERTS, and why not something stronger: a reference carrying an
explicit `| default(...)` is allowed to be unresolvable, because that is a
deliberate statement that the key may be absent. Requiring *every* key to
resolve would be satisfied by adding `| default('')` everywhere, which turns the
guard into a no-op. So the invariant is: a reference with NO default must
resolve against the RAW merged values -- the same data Ansible actually sees.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE_DIR = REPO_ROOT / "infra/ansible"
VALUES_DIR = REPO_ROOT / "infra/config/values"

#: Environments whose merged values a playbook may be run against.
ENVIRONMENTS = ("staging", "prod")

#: `config.<dotted.path>` as it appears in a playbook or role.
CONFIG_REF = re.compile(r"\bconfig\.([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)")

#: A reference only reaches Ansible's templating if it sits inside Jinja
#: delimiters. Scanning raw lines instead matches filenames and paths --
#: `config.yaml` in a `src:`, `config.d/` in a directory, `config.py` in a
#: comment -- and a guard that reports things which are obviously not bugs is a
#: guard people learn to skim. Restricting to Jinja spans is the principled
#: version of what would otherwise be an ever-growing blocklist.
JINJA_SPAN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)

#: Trailing segments that are Jinja METHODS on an already-resolved value, not
#: further keys: `config.edge.traefik.dns_resolver_1.split(':')`.
JINJA_METHODS = frozenset({"split", "keys", "values", "items", "get", "lower", "upper", "strip"})


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _raw_merged(env: str) -> dict:
    """common + <env>, merged exactly as Ansible's two `include_vars` do.

    Deliberately NOT `ConfigLoader`: the whole point is to see what Ansible sees,
    and loading through the toolkit would make every derived key resolve and the
    test pass on the case it exists to catch.
    """
    return _deep_merge(_load(VALUES_DIR / "common.yaml"), _load(VALUES_DIR / f"{env}.yaml"))


def _resolves(config: dict, dotted: str) -> bool:
    node = config
    for part in dotted.split("."):
        if part in JINJA_METHODS:
            return True  # a method call on whatever resolved so far
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _references() -> list[tuple[pathlib.Path, int, str, str]]:
    """Every `config.*` reference in the Ansible tree, with its source line."""
    found = []
    for path in sorted(ANSIBLE_DIR.rglob("*.yml")) + sorted(ANSIBLE_DIR.rglob("*.j2")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for span in JINJA_SPAN.finditer(line):
                for match in CONFIG_REF.finditer(span.group(0)):
                    found.append((path, lineno, match.group(1), line.strip()))
    return found


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_undefaulted_config_key_resolves(env: str) -> None:
    """A key with no `| default(...)` must exist in the raw merged values."""
    config = _raw_merged(env)

    broken = [
        (path.relative_to(REPO_ROOT), lineno, dotted)
        for path, lineno, dotted, line in _references()
        # An explicit default is a deliberate statement that the key may be
        # absent, so it is exempt. Anything else is a promise Ansible will keep
        # only if the key is really there.
        if "default(" not in line and not _resolves(config, dotted)
    ]

    assert not broken, (
        f"These Ansible references read a `config.*` key that does NOT exist in the raw "
        f"{env} values, so the play fails at deploy time with "
        f"\"object of type 'dict' has no attribute ...\":\n"
        + "\n".join(f"  {p}:{n} -> config.{d}" for p, n, d in broken)
        + "\n\nAnsible reads these files through `include_vars`, which does NOT run "
        "`ConfigLoader`, so no derivation the loader performs is visible to it "
        "(SSOT-014c fills `edge.traefik.acme_email` this way).\n\n"
        "Either add the key to the values file, or reference the SSOT it is derived "
        "from with an explicit `| default(<source>, true)` mirroring the loader's own "
        "falsy test. Do NOT add a bare `| default('')` to silence this — an empty "
        "value usually produces a broken config rather than an absent one."
    )


def test_the_scan_finds_references_at_all() -> None:
    """Guard the guard: an empty scan makes the assertion above vacuous.

    If the regex or the walk breaks, `broken` is empty and every environment
    passes while checking nothing. This fails first instead.
    """
    refs = _references()
    assert len(refs) > 50, (
        f"Only {len(refs)} `config.*` references found in {ANSIBLE_DIR}, expected many more. "
        "The scan is probably broken, which would make the resolution test above pass "
        "vacuously — fix the scan before trusting it."
    )


def test_the_known_derived_key_is_still_derived() -> None:
    """The specific key that caused #1543, asserted from the raw values.

    If `edge.traefik.acme_email` were ever added to a values file, every
    `| default(...)` guarding it would become dead code that still LOOKS load
    bearing. This says plainly which world we are in.
    """
    for env in ENVIRONMENTS:
        traefik = _raw_merged(env).get("edge", {}).get("traefik", {})
        assert "acme_email" not in traefik, (
            f"`edge.traefik.acme_email` now exists in the raw {env} values. That is not "
            "wrong in itself, but it contradicts SSOT-014c, which derives it from "
            "`apps.contact.email` in the config loader. Decide which is the SSOT: either "
            "remove this key again, or remove the derivation and the `| default(...)` "
            "fallbacks in the playbooks, which are now dead code that still reads as "
            "load bearing."
        )
