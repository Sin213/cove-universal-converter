"""Release-version validation shared by packaging scripts and tests."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

PROJECT_VERSION = "2.4.0"
_VERSION_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:[.-]?(?:a|b|rc|dev|post)\d*)?(?:\+[a-z0-9]+(?:[.-][a-z0-9]+)*)?$",
    re.IGNORECASE,
)


def validate_version(value: str) -> str:
    """Return a safe normalized release version or raise ``ValueError``."""
    version = value.strip()
    if version.startswith("v"):
        version = version[1:]
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(
            f"invalid release version {value!r}; expected a version such as 2.4.0 or 2.4.1rc1"
        )
    return version


def version_from_pyproject(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        value = tomllib.load(stream)["project"]["version"]
    return validate_version(value)


def validate_release(
    value: str, *, project_file: str | Path | None = None, tag: str | None = None
) -> str:
    """Validate a requested version against package metadata and an optional tag."""
    version = validate_version(value)
    if project_file is not None:
        metadata_version = version_from_pyproject(project_file)
        if PROJECT_VERSION != metadata_version:
            raise ValueError(
                "runtime version does not match pyproject.toml: "
                f"{PROJECT_VERSION} != {metadata_version}"
            )
        if version != metadata_version:
            raise ValueError(
                f"requested release version {version} does not match "
                f"pyproject.toml version {metadata_version}"
            )
    if tag is not None:
        tag_version = validate_version(tag)
        if tag_version != version:
            raise ValueError(
                f"release version {version} does not match tag version {tag_version}"
            )
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--tag")
    args = parser.parse_args(argv)
    try:
        print(validate_release(args.version, project_file=args.project, tag=args.tag))
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
