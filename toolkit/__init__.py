from importlib.metadata import metadata, version

from toolkit.core.io import force_utf8_stdio

force_utf8_stdio()

__version__ = version("toolkit")
_pkg = metadata("toolkit")
__author__ = _pkg.get("Author", "unknown")
__email__ = _pkg.get("Author-email", "unknown")
