"""Validate package versions and release notes before building distributions."""

from __future__ import annotations

import argparse
import logging
import os
import re
import tomllib
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


def check_release(root: Path, *, release: bool = False, tag: str | None = None) -> str:
    """Check project metadata and return the package version.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.
    release : bool, optional
        Require a dated, nonempty changelog entry for this version.
    tag : str, optional
        Tag to compare with ``v{version}``.

    Returns
    -------
    str
        Validated project version.

    Raises
    ------
    ValueError
        Versions disagree or the release notes are missing or invalid.
    """
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    packages = tomllib.loads((root / "uv.lock").read_text())["package"]
    locked = [p["version"] for p in packages if p["name"] == project["name"]]
    if locked != [version]:
        raise ValueError(f"uv.lock must contain one {project['name']} entry at version {version}")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} must match v{version}")
    if release:
        lines = (root / "docs/changelog.rst").read_text().splitlines()
        headings = [
            i
            for i in range(len(lines) - 1)
            if lines[i].strip()
            and len(lines[i + 1]) >= len(lines[i])
            and set(lines[i + 1]) == {"-"}
        ]
        matching = [i for i in headings if lines[i].split(maxsplit=1)[0] == f"v{version}"]
        if len(matching) != 1:
            raise ValueError(f"Expected one dated changelog entry for v{version}")
        start = matching[0]
        match = re.fullmatch(rf"v{re.escape(version)} \((\d{{4}}-\d{{2}}-\d{{2}})\)", lines[start])
        if match is None:
            raise ValueError(f"Changelog heading must be v{version} (YYYY-MM-DD)")
        date.fromisoformat(match.group(1))
        end = next((i for i in headings if i > start), len(lines))
        if not any(line.strip() for line in lines[start + 2 : end]):
            raise ValueError(f"Changelog entry for v{version} is empty")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--tag")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        version = check_release(Path.cwd(), release=args.release, tag=args.tag)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"Release validation failed: {error}\n")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            stream.write(f"version={version}\n")
    log.info("Validated pqfilt %s", version)
