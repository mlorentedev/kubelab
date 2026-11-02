"""Whether an image reference pins a version, shared by the image checks."""

from __future__ import annotations


def versioned(image: str) -> bool:
    """A digest, or a tag that carries a version number and is not `latest`."""
    if "@sha256:" in image:
        return True
    name = image.split("/")[-1]
    tag = name.split(":", 1)[1] if ":" in name else ""
    return tag not in ("", "latest") and any(ch.isdigit() for ch in tag)
