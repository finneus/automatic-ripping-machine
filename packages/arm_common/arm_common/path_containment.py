"""`safe_join` / `is_within`: the one containment guard for a path built from
untrusted input (a request, a theme id, a name read off a disc). Both
resolve symlinks before the check, so a link inside the root that points
outward is caught, as are `..` and absolute names.

`is_relative_path`: the lexical check for a media output path rendered from a
session template. It refuses an absolute path and a `..` segment but follows
symlinks on purpose: a media sub-folder may link to another mount.
"""

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath


def _contained(resolved: Path, base: Path, allow_root: bool) -> bool:
    return allow_root if resolved == base else resolved.is_relative_to(base)


def is_within(path: Path, root: Path, *, allow_root: bool = False) -> bool:
    """True when `path` resolves inside `root`; `root` itself only with `allow_root`."""
    return _contained(path.resolve(), root.resolve(), allow_root)


def safe_join(base: Path, relative: str | Path, *, allow_root: bool = False) -> Path:
    """Join `relative` onto `base` and return the resolved path, proven inside `base`.

    Raises ValueError when the result lands outside `base` (`..`, an absolute
    name, an outward symlink), or is `base` itself unless `allow_root`.
    """
    base = base.resolve()
    target = (base / relative).resolve()
    if not _contained(target, base, allow_root):
        raise ValueError(f"path {str(relative)!r} escapes {base}")
    return target


def is_relative_path(relative: str | PurePath) -> bool:
    """True when `relative`, joined to any root, stays under it: not absolute and no `..` segment."""
    path = PurePosixPath(relative)
    return not path.is_absolute() and ".." not in path.parts
