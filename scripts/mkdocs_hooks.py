"""Keep repository-local source links usable in the published documentation.

MkDocs only publishes files in docs/. The existing reference pages deliberately link
to package source, notebooks, and the repository README. Resolve those links to
their GitHub source locations while retaining local relative links within docs/.
scripts/check_docs.py validates the original local targets and anchors in CI.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

REPO_URL = "https://github.com/MarineCast/toolkit-seascape/blob/main/"
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LINK = re.compile(r"(!?\[[^\]\n]*\]\()([^\s)]+)(\))")


def on_page_markdown(markdown: str, page, config, files) -> str:
    source = DOCS / page.file.src_path

    def replace(match: re.Match[str]) -> str:
        target = match.group(2)
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match.group(0)
        resolved = (source.parent / parsed.path).resolve()
        if resolved == DOCS / "README.md":
            destination = Path(
                os.path.relpath(DOCS / "index.md", source.parent)
            ).as_posix()
            if parsed.fragment:
                destination += "#" + parsed.fragment
            return match.group(1) + destination + match.group(3)
        if resolved.is_relative_to(DOCS) or not resolved.is_relative_to(ROOT):
            return match.group(0)
        if not resolved.exists():
            raise ValueError(f"Broken repository link in {source}: {target}")
        relative = resolved.relative_to(ROOT).as_posix()
        url = REPO_URL + quote(relative, safe="/")
        if parsed.fragment:
            url += "#" + parsed.fragment
        return match.group(1) + url + match.group(3)

    return LINK.sub(replace, markdown)
