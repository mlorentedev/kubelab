from importlib.metadata import metadata, version

__version__ = version("toolkit")
_pkg = metadata("toolkit")
__author__ = _pkg.get("Author", "unknown")
__email__ = _pkg.get("Author-email", "unknown")
