"""The product contract, ``kubelab.yaml`` (ADR-067 D2, IDP-042).

A product declares what it owns in one file at its repository root: image
repository, port, health path, a hostname per environment, auth level and the
names of the secrets it expects. Anyone who can push to the product repository
writes that file, so it is treated as attacker-shaped data: parsed with a safe
loader that also refuses duplicate keys, validated against a closed model with
anchored patterns, and refused with ERROR / WHY / FIX rather than a traceback.

What a contract may NOT say is as important as what it may: where it is
fetched from and where the result is pushed come from the registry and the
receiver's own repository, never from the contract (proposal design point 2).
Checks against the registry and the platform (the derived image, the secret
catalog, hostname collisions) live in a later layer; this module only answers
"is this a well-formed contract".

The model is the single definition: ``toolkit/schemas/kubelab-product.schema.json``
is generated from it and a test keeps the two equal.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Hashable
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from pydantic_core import ErrorDetails

SCHEMA_RESOURCE = ("schemas", "kubelab-product.schema.json")
SCHEMA_ID = "https://raw.githubusercontent.com/mlorentedev/kubelab/master/toolkit/schemas/kubelab-product.schema.json"

#: Keys a contract might use to say where it lives. None is in the schema, so
#: they are refused like any unknown key, with a message that says why.
REPOSITORY_KEYS = frozenset({"repository", "repo", "source", "remote"})

# Patterns are compiled by pydantic's Rust engine and published in the JSON
# Schema for product authors' own validators: no lookarounds, no backreferences.
# Lengths are capped with max_length instead.
_HOSTNAME = r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$"
_IMAGE = r"^[a-z0-9]+([.-][a-z0-9]+)*(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)+$"
_HEALTH_PATH = r"^/[A-Za-z0-9._~/-]*$"
_SECRET_NAME = r"^[a-z0-9_]+(\.[a-z0-9_]+)*$"

Hostname = Annotated[str, StringConstraints(max_length=253, pattern=_HOSTNAME)]
SecretName = Annotated[str, StringConstraints(max_length=200, pattern=_SECRET_NAME)]


class ContractError(Exception):
    """A contract refusal, worded for the product author who has to fix it."""

    def __init__(self, error: str, why: str, fix: str) -> None:
        super().__init__(error)
        self.error = error
        self.why = why
        self.fix = fix

    def __str__(self) -> str:
        return f"ERROR: {self.error}\nWHY: {self.why}\nFIX: {self.fix}"

    def as_dict(self) -> dict[str, str]:
        return {"error": self.error, "why": self.why, "fix": self.fix}


class Hostnames(BaseModel):
    """The public hostname of the product in each kubelab environment."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    staging: Hostname = Field(description="Hostname served by the staging cluster, e.g. staging.example.dev.")
    prod: Hostname = Field(description="Hostname served by the prod cluster, e.g. example.dev.")


class Contract(BaseModel):
    """What a product declares about itself to be deployed on kubelab."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        title="kubelab product contract",
        json_schema_extra={"$id": SCHEMA_ID, "$schema": "https://json-schema.org/draft/2020-12/schema"},
    )

    schema_version: Literal[1] = Field(description="Version of this schema the contract is written against.")
    image: str = Field(
        max_length=255,
        pattern=_IMAGE,
        description="Image repository without tag or digest; kubelab pins the tag it deploys.",
    )
    port: int = Field(ge=1, le=65535, description="Port the container listens on inside the cluster.")
    health_path: str = Field(
        max_length=256,
        pattern=_HEALTH_PATH,
        description="HTTP path that answers 2xx when the container is healthy.",
    )
    hostnames: Hostnames
    auth: Literal["public", "forwardauth", "oidc"] = Field(
        description=(
            "public: no auth; forwardauth: Authelia in front of every request; oidc: the app is an OIDC client."
        ),
    )
    secrets: list[SecretName] = Field(
        default_factory=list,
        description="Names of the secrets the product expects. Values never appear here; the operator sets them.",
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version_is_not_a_bool(cls, value: Any) -> Any:
        # Literal[1] accepts True even in strict mode (True == 1, same hash).
        if isinstance(value, bool):
            raise ValueError("must be the integer 1, not a boolean")
        return value


class _DuplicateKeyError(Exception):
    def __init__(self, key: Hashable, line: int) -> None:
        super().__init__(key)
        self.key = key
        self.line = line


class _MergeKeyError(Exception):
    def __init__(self, line: int) -> None:
        super().__init__(line)
        self.line = line


class _UniqueKeyLoader(yaml.SafeLoader):
    """``SafeLoader`` that refuses a mapping declaring the same key twice, or merging another one in."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise _MergeKeyError(key_node.start_mark.line + 1)
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, Hashable):
                if key in seen:
                    raise _DuplicateKeyError(key, key_node.start_mark.line + 1)
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _field(loc: tuple[int | str, ...]) -> str:
    """``("hostnames", "prod")`` -> ``hostnames.prod``; ``("secrets", 0)`` -> ``secrets[0]``."""
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


#: A FIX for the fields where a generic one would not tell the author what to write.
_FIELD_FIX = {
    "schema_version": "set schema_version: 1 (an integer, not a string or a boolean).",
    "image": "give the image repository alone, e.g. docker.io/<owner>/<product>, with no :tag or @digest.",
    "port": "set port to the container's listening port, an integer from 1 to 65535 (not quoted).",
    "health_path": "give an HTTP path that starts with '/', e.g. /healthz.",
    "hostnames": "declare exactly hostnames.staging and hostnames.prod, each a lowercase FQDN with no scheme or path.",
    "auth": "set auth to one of: public, forwardauth, oidc.",
    "secrets": "list secret names as dotted lowercase keys, e.g. apps.platform.<app>.api_key; values never go here.",
}

_WHY = {
    "extra_forbidden": "the schema is closed, so a misspelt or unsupported key is refused instead of silently ignored.",
    "missing": "the field is required: kubelab cannot render the product's configuration without it.",
}


def _explain(field: str, detail: ErrorDetails) -> tuple[str, str]:
    """Return (why, fix) for one pydantic error on ``field``."""
    top = str(detail["loc"][0]) if detail["loc"] else ""
    if detail["type"] == "extra_forbidden" and top in REPOSITORY_KEYS:
        return (
            "where a product is fetched from and where its PR is pushed come from kubelab's product registry, "
            "never from the contract, so a contract cannot redirect either.",
            f"remove '{top}'; ask the kubelab operator to change the registry entry if the repository moved.",
        )
    why = _WHY.get(detail["type"], "the value does not meet the constraint the schema declares for this field.")
    fix = _FIELD_FIX.get(top, f"remove '{field}' or correct it.")
    return why, f"{fix} Schema: {SCHEMA_ID}"


def _refusal(path: Path, exc: ValidationError) -> ContractError:
    errors = exc.errors()
    first = errors[0]
    field = _field(first["loc"])
    more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    why, fix = _explain(field, first)
    return ContractError(f"{path}: field '{field}': {first['msg']}{more}", why, fix)


def load_document(path: Path) -> dict[str, Any]:
    """Read ``path`` as one YAML mapping, refusing unreadable, malformed or duplicate-key input."""
    try:
        text = path.read_text()
    except OSError as e:
        raise ContractError(
            f"{path}: cannot be read ({e.strerror})",
            "the contract is the only input kubelab has about the product, so a missing file stops the deploy.",
            "commit kubelab.yaml at the repository root, at the commit the image was built from.",
        ) from None
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except _DuplicateKeyError as e:
        raise ContractError(
            f"{path}: field '{e.key}' is declared twice (duplicate key at line {e.line})",
            "YAML keeps only the last value, so a reader of the first one would be misled about what deploys.",
            f"keep a single '{e.key}' key.",
        ) from None
    except _MergeKeyError as e:
        raise ContractError(
            f"{path}: a YAML merge key '<<' is used at line {e.line}",
            "an explicit key silently overrides a merged one, so a reader of the merged block would be misled.",
            "write every field out; a contract is short enough not to need anchors.",
        ) from None
    except yaml.YAMLError as e:
        raise ContractError(
            f"{path}: is not valid YAML ({e})",
            "a contract that cannot be parsed cannot be validated.",
            "fix the YAML syntax at the line and column reported above.",
        ) from None
    if not isinstance(data, dict):
        raise ContractError(
            f"{path}: the document must be a mapping of fields, got {type(data).__name__}",
            "every contract field is a top-level key.",
            f"start from the schema at {SCHEMA_ID}.",
        )
    return data


def validate_contract(path: Path) -> Contract:
    """Parse and validate the contract at ``path``; raise ``ContractError`` on any refusal."""
    path = Path(path)
    data = load_document(path)
    try:
        return Contract.model_validate(data)
    except ValidationError as e:
        raise _refusal(path, e) from None


def schema_text() -> str:
    """The JSON Schema generated from ``Contract``, serialised the way it is committed."""
    return json.dumps(Contract.model_json_schema(), indent=2, sort_keys=True) + "\n"


def schema_path() -> Path:
    """The committed schema inside the installed package (ADR-067 D8: a pinned install carries it)."""
    return Path(str(files("toolkit").joinpath(*SCHEMA_RESOURCE)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m toolkit.features.product_contract")
    parser.add_argument("--write-schema", action="store_true", help="regenerate the committed JSON Schema")
    args = parser.parse_args(argv)
    if not args.write_schema:
        parser.print_help()
        return 2
    path = schema_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema_text())
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
