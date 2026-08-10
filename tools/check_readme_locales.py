#!/usr/bin/env python3
"""Validate that every localized README is complete and navigable."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LOCALIZED_READMES = (
    "docs/locales/zh-CN.md",
    "docs/locales/en.md",
    "docs/locales/ja.md",
    "docs/locales/ko.md",
)
SECTION_MARKERS = (
    "status",
    "features",
    "requirements",
    "workflow",
    "local-assets",
    "architecture",
    "invariants",
    "testing",
    "packaging",
    "privacy",
    "docs",
    "license",
)
REQUIRED_REFERENCES = (
    "../../AGENTS.md",
    "../AGENT_HANDOFF.md",
    "../ARCHITECTURE.md",
    "../AI_CONTEXT.md",
    "../OPTIMIZATION_EXTENSION_ROADMAP.md",
    "../../THIRD_PARTY_NOTICES.md",
    "../../LICENSE",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def validate_readmes(root: Path = ROOT) -> list[str]:
    """Return human-readable validation errors without mutating the tree."""

    errors: list[str] = []
    hub_path = root / "README.md"
    if not hub_path.is_file():
        return ["README.md: missing language hub"]
    hub = hub_path.read_text(encoding="utf-8")
    for filename in LOCALIZED_READMES:
        if filename not in hub:
            errors.append(f"README.md: missing link to {filename}")
    for reference in ("AGENTS.md", "docs/AGENT_HANDOFF.md"):
        if reference not in hub:
            errors.append(f"README.md: missing {reference}")

    repository_root = root.resolve()
    for filename in LOCALIZED_READMES:
        path = root / filename
        if not path.is_file():
            errors.append(f"{filename}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        if len(text) < 1_500:
            errors.append(f"{filename}: too short to be a standalone guide")
        positions: list[int] = []
        for section in SECTION_MARKERS:
            marker = f"<!-- section:{section} -->"
            count = text.count(marker)
            if count != 1:
                errors.append(
                    f"{filename}: expected one {marker}, found {count}"
                )
            else:
                positions.append(text.index(marker))
        if positions != sorted(positions):
            errors.append(f"{filename}: shared sections are out of order")
        for sibling in LOCALIZED_READMES:
            sibling_name = Path(sibling).name
            if sibling_name not in text:
                errors.append(
                    f"{filename}: language nav misses {sibling_name}"
                )
        for reference in REQUIRED_REFERENCES:
            if reference not in text:
                errors.append(f"{filename}: missing required reference {reference}")

        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(repository_root)
            except ValueError:
                errors.append(
                    f"{filename}: local link escapes repository: {raw_target}"
                )
                continue
            if not resolved.exists():
                errors.append(f"{filename}: broken local link {raw_target}")
    return errors


def main() -> int:
    errors = validate_readmes()
    if errors:
        for error in errors:
            print(error)
        return 1
    print(
        f"README locale check passed: {len(LOCALIZED_READMES)} complete guides"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
