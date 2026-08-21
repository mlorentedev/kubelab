"""The local kubeconfig path has one owner; nothing else may re-derive it.

``~/.kube/kubelab-<env>-config`` is declared once, by
``toolkit/features/k8s_kubeconfig.py`` (``_KUBECONFIG_OUT_PATTERN``), and read
through its public helper ``output_path(env)``. Six other modules used to build
the same string inline — four with an f-string on ``{env}``, two with the
environment baked in (``kubelab-hub-config``, ``kubelab-staging-config``).

A copy is not merely untidy here: it fails *quietly*. Change the pattern and the
owner starts writing the new path while every copy keeps pointing at the old
one; kubectl then runs against a kubeconfig nobody refreshed, or against none at
all, and the only symptom is a command that behaves as if the cluster changed.
Nothing goes red.

This guard is a grep, deliberately. It cannot be satisfied by importing the
helper somewhere and still hand-building the string next to it, and it catches a
new copy in a module that no unit test exercises — which is how five of the six
survived in the first place.

Anchoring (docs/lessons/lesson-357): the pattern below is a **literal** written
into this file, never derived from the files being scanned. A guard whose
expected value is computed from its actual value passes by construction. For the
same reason ``test_the_owner_still_matches_the_pattern`` exists: if the owner
ever rewords its constant out of this shape, the scan would go on finding
nothing — green forever, checking nothing. The positive control is what keeps
the regex itself falsifiable.
"""

from __future__ import annotations

import pathlib
import re

#: Literal shape of a built kubeconfig filename: ``kubelab-`` + an environment
#: (an f-string/format placeholder such as ``{env}``, or a hardcoded name like
#: ``hub``) + ``-config``. The prose form ``kubelab-<env>-config`` used in
#: docstrings does not match, and should not: prose never evaluates to a path.
KUBECONFIG_NAME_PATTERN = re.compile(r"kubelab-(?:\{[^}]*\}|[A-Za-z0-9_]+)-config")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLKIT_ROOT = REPO_ROOT / "toolkit"

#: The one module allowed to spell the path out. Everything else calls
#: ``toolkit.features.k8s_kubeconfig.output_path(env)``.
OWNER = TOOLKIT_ROOT / "features" / "k8s_kubeconfig.py"


def _offending_lines() -> list[str]:
    """Every ``toolkit/`` line outside the owner that builds a kubeconfig name."""
    hits: list[str] = []
    for path in sorted(TOOLKIT_ROOT.rglob("*.py")):
        if path == OWNER:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if KUBECONFIG_NAME_PATTERN.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    return hits


def test_only_k8s_kubeconfig_derives_the_kubeconfig_path() -> None:
    offenders = _offending_lines()
    assert not offenders, (
        "kubeconfig path re-derived outside toolkit/features/k8s_kubeconfig.py; "
        "call output_path(env) instead (str() it if a str is needed):\n  " + "\n  ".join(offenders)
    )


def test_the_owner_still_matches_the_pattern() -> None:
    """Positive control: the shape this guard hunts for must still exist."""
    assert KUBECONFIG_NAME_PATTERN.search(OWNER.read_text()), (
        f"{OWNER.relative_to(REPO_ROOT)} no longer contains a "
        f"{KUBECONFIG_NAME_PATTERN.pattern!r} literal — the scan above is now "
        "looking for a shape that exists nowhere and can never fail. Update "
        "KUBECONFIG_NAME_PATTERN to the new shape."
    )
