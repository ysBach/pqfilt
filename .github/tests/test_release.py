"""Release metadata checks, run with the build job's Python 3.13 interpreter."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_release", Path(__file__).parents[1] / "scripts/check_release.py"
)
assert spec is not None and spec.loader is not None
release_checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_checks)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal package with matching release metadata."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1.2.3"\n')
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "example"\nversion = "1.2.3"\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/changelog.rst").write_text(
        "v1.2.3 (2026-09-07)\n--------------------\n\n* Fixed filtering.\n"
    )
    return tmp_path


def test_matching_release(project: Path) -> None:
    assert release_checks.check_release(project, release=True, tag="v1.2.3") == "1.2.3"


def test_ci_does_not_require_release_notes(project: Path) -> None:
    (project / "docs/changelog.rst").unlink()
    assert release_checks.check_release(project) == "1.2.3"


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2.4", "v1.2.3-extra", ""])
def test_wrong_tag(project: Path, tag: str) -> None:
    with pytest.raises(ValueError, match="must match"):
        release_checks.check_release(project, release=True, tag=tag)


@pytest.mark.parametrize(
    "lock",
    [
        "package = []\n",
        '[[package]]\nname = "example"\nversion = "1.2.2"\n',
        '[[package]]\nname = "example"\nversion = "1.2.3"\n' * 2,
    ],
)
def test_invalid_lock_entry(project: Path, lock: str) -> None:
    (project / "uv.lock").write_text(lock)
    with pytest.raises(ValueError, match="uv.lock"):
        release_checks.check_release(project)


@pytest.mark.parametrize(
    "notes",
    [
        "Unreleased\n----------\n\n* Pending fix.\n",
        "v1.2.3\n------\n\n* Fix.\n",
        "v1.2.3 (2026-02-30)\n--------------------\n\n* Fix.\n",
        "v1.2.3 (2026-09-07)\n--------------------\n\n",
        "v1.2.3 (2026-09-07)\n--------------------\n\nv1.2.2 (2026-08-01)\n"
        "--------------------\n\n* Older fix.\n",
        "v1.2.3 (2026-09-07)\n--------------------\n\n* Fix.\n\n" * 2,
    ],
)
def test_invalid_release_notes(project: Path, notes: str) -> None:
    (project / "docs/changelog.rst").write_text(notes)
    with pytest.raises(ValueError):
        release_checks.check_release(project, release=True)


def test_prerelease_version(project: Path) -> None:
    for filename in ("pyproject.toml", "uv.lock", "docs/changelog.rst"):
        path = project / filename
        path.write_text(path.read_text().replace("1.2.3", "1.2.3rc1").replace("----", "------"))
    assert release_checks.check_release(project, release=True, tag="v1.2.3rc1") == "1.2.3rc1"
