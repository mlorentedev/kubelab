"""The product registry, ``infra/config/products.yaml`` (ADR-067 D2, IDP-042).

The registry is the list of products kubelab admits, and the trust anchor for
everything a product's contract says about itself: a product absent from it is
refused, and what it records (the repository, the forge, the dispatch event
types) is never taken from the contract. It is operator-owned data, read as a
standalone toolkit input rather than flattened into the values (proposal Q1).

The platform apps the generators and ``promote`` iterate are read from here, in
file order, so admitting a product is a registry entry rather than an edit to a
literal tuple (#1815). An entry whose forge is ``in-tree`` (``api``, ADR-048) has
no remote repository and receives no dispatch: it is a platform app whose values
stay hand-authored, not a contract-managed product (proposal design point 3).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from toolkit.config.settings import settings

REGISTRY_RELPATH = Path("infra") / "config" / "products.yaml"
COMMON_VALUES_RELPATH = Path("infra") / "config" / "values" / "common.yaml"

# App names key the flattened values (``APPS_PLATFORM_<NAME>_*``), so they are
# limited to what an env-var segment can carry without translation.
_APP_NAME = r"^[a-z][a-z0-9]{0,39}$"
_REPOSITORY = r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"
_EVENT = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_IMAGE_NAME = r"^[a-z0-9]+([._-][a-z0-9]+)*$"

EventType = Annotated[str, StringConstraints(max_length=100, pattern=_EVENT)]


class RegistryError(ValueError):
    """The registry file is unreadable or invalid, or refuses what was asked of it."""


class UnknownEventError(RegistryError):
    """A dispatch event type that no registered product claims."""


class Events(BaseModel):
    """The ``repository_dispatch`` event types a product's CI sends, per lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    staging: EventType | None = None
    prod: EventType | None = None


class Product(BaseModel):
    """One admitted product."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    forge: Literal["github", "gitea", "in-tree"]
    repository: Annotated[str, StringConstraints(pattern=_REPOSITORY)] | None = None
    receiver: Literal["legacy", "generic"] | None = None
    events: Events = Field(default_factory=Events)
    # Only where the derived image name is wrong (Q7). It lives here, not in the
    # contract, so a product cannot grant itself another image.
    image_name: Annotated[str, StringConstraints(max_length=128, pattern=_IMAGE_NAME)] | None = None

    @model_validator(mode="after")
    def _forge_decides_the_shape(self) -> Product:
        if self.forge == "in-tree":
            named = [field for field in ("repository", "receiver", "events") if field in self.model_fields_set]
            if named:
                raise ValueError(
                    f"an in-tree product has no remote repository and receives no dispatch; remove {', '.join(named)}"
                )
        else:
            missing = [field for field in ("repository", "receiver") if getattr(self, field) is None]
            if missing:
                raise ValueError(f"a {self.forge} product needs {', '.join(missing)}")
        return self

    @property
    def contract_managed(self) -> bool:
        return self.forge != "in-tree"


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    products: dict[str, Product]

    @field_validator("products")
    @classmethod
    def _names_and_events(cls, products: dict[str, Product]) -> dict[str, Product]:
        if not products:
            raise ValueError("the registry admits no products")
        bad = [name for name in products if not re.fullmatch(_APP_NAME, name)]
        if bad:
            raise ValueError(f"app name {', '.join(map(repr, bad))} must match {_APP_NAME}")
        claimed: dict[str, str] = {}
        for name, product in products.items():
            for event in (product.events.staging, product.events.prod):
                if event is None:
                    continue
                if event in claimed:
                    raise ValueError(f"event type '{event}' is claimed by both {claimed[event]} and {name}")
                claimed[event] = name
        return products


class _UniqueKeyLoader(yaml.SafeLoader):
    """A safe loader that refuses a repeated mapping key instead of keeping the last one."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key '{key}'", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def registry_path() -> Path:
    return settings.project_root / REGISTRY_RELPATH


def load_registry(path: Path | None = None) -> Registry:
    """Load and validate the registry; ``RegistryError`` names the file on any refusal."""
    return _load(Path(path) if path is not None else registry_path())


@lru_cache(maxsize=None)
def _load(path: Path) -> Registry:
    try:
        # A SafeLoader subclass: no Python tags, only the duplicate-key refusal added.
        data = yaml.load(path.read_text(), Loader=_UniqueKeyLoader)  # noqa: S506
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"{path}: cannot read the product registry: {exc}") from exc
    try:
        return Registry.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or '(top level)'}: {err['msg']}" for err in exc.errors()
        )
        raise RegistryError(f"{path}: invalid product registry: {problems}") from exc


def platform_apps(path: Path | None = None) -> tuple[str, ...]:
    """The admitted products, in registry order (the generators' output order)."""
    return tuple(load_registry(path).products)


def app_for_event(event: str, path: Path | None = None) -> str:
    """The app that owns a dispatch event type. The payload never names the app (AC1)."""
    resolved = Path(path) if path is not None else registry_path()
    for name, product in load_registry(resolved).products.items():
        if event in (product.events.staging, product.events.prod):
            return name
    raise UnknownEventError(
        f"event type '{event}' is not mapped to any product in {resolved}; "
        "a product is admitted by adding its entry to the registry"
    )


def platform_registry() -> str:
    """The platform's image registry (``registry`` in ``common.yaml``), read without SOPS."""
    path = settings.project_root / COMMON_VALUES_RELPATH
    value = (yaml.safe_load(path.read_text()) or {}).get("registry")
    if not value:
        raise RegistryError(f"{path}: no top-level `registry` to derive product images from")
    return str(value)


def derived_image(app: str, path: Path | None = None) -> str:
    """The image repository the platform derives for a product (Q7): ``<registry>/<image_name or app>``.

    The platform registry already ends in the owner (``docker.io/mlorentedev``), so
    the rule ``<registry>/<owner>/<product>`` reads ``<registry>/<product>``. A
    contract's ``image`` must equal this; an in-tree product has no contract, and its
    hand-authored image (``kubelab-api``) is not what the rule yields, so it refuses.
    """
    resolved = Path(path) if path is not None else registry_path()
    product = load_registry(resolved).products.get(app)
    if product is None:
        raise RegistryError(f"'{app}' is not a registered product in {resolved}")
    if not product.contract_managed:
        raise RegistryError(
            f"'{app}' is in-tree in {resolved}: its image is hand-authored in apps.platform.{app}.image_name, "
            "not derived from a contract"
        )
    return f"{platform_registry()}/{product.image_name or app}"
