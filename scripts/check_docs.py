"""Offline documentation, template and generated-reference checks; no source acquisition."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from check_quickstart import fenced_example

from seascape.cli import DOWNLOAD_FAMILIES, FAMILIES, initialize_workspace
from seascape.cli import main as cli_main
from seascape.maintenance.update_seascape_docs import (
    END_MARKER,
    START_MARKER,
    render_product_index,
)
from seascape.preflight import preflight_build
from seascape.workflow import DOMAIN_LAYER_STAGES, stage_names

STAGE_START = "<!-- BEGIN GENERATED STAGE INPUTS -->"
STAGE_END = "<!-- END GENERATED STAGE INPUTS -->"


def _text(path: Path) -> str:
    if path.suffix == ".ipynb":
        return "\n".join(
            "".join(cell["source"])
            for cell in json.loads(path.read_text())["cells"]
            if cell["cell_type"] == "markdown"
        )
    return path.read_text()


def _prose(text: str) -> str:
    return re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text, flags=re.M | re.S)


def anchors(text: str) -> set[str]:
    """GitHub-style heading slugs, including repeated headings and explicit anchors."""
    result = set(re.findall(r'<(?:a|h\d)\s+(?:id|name)="([^"]+)"', text))
    counts: dict[str, int] = {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", _prose(text), re.M):
        title = re.sub(r"<[^>]+>", "", title)
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + (f"-{count}" if count else ""))
    return result


def check_links(root: Path, documents: list[Path]) -> int:
    checked = 0
    for document in documents:
        text = _prose(_text(document))
        if not re.search(r"^#\s+\S", text, re.M):
            raise ValueError(f"Missing document heading: {document.relative_to(root)}")
        for target in re.findall(r"!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or parsed.netloc:
                continue  # External URL availability is a separate, optional network check.
            path = (
                (document.parent / unquote(parsed.path)).resolve()
                if parsed.path
                else document
            )
            if not path.is_relative_to(root.resolve()) or not path.exists():
                raise ValueError(
                    f"Broken local link: {document.relative_to(root)} -> {target}"
                )
            if parsed.fragment and path.suffix in {".md", ".ipynb"}:
                if unquote(parsed.fragment) not in anchors(_text(path)):
                    raise ValueError(
                        f"Broken heading link: {document.relative_to(root)} -> {target}"
                    )
            checked += 1
    return checked


def check_commands(documents: list[Path]) -> None:
    stages = set(stage_names())
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            cli_main(["--help"])
        except SystemExit as exc:
            if exc.code != 0:
                raise
    choices = re.search(r"\{([^}]+)\}", output.getvalue())
    if not choices:
        raise ValueError("Cannot find command choices in production CLI help")
    commands = set(choices[1].split(","))
    for document in documents:
        text = "\n".join(
            re.findall(r"^```(?:sh|bash)\n(.*?)^```", _text(document), re.M | re.S)
        )
        for stage in re.findall(r"--(?:only|skip)\s+(seascape-[\w-]+)", text):
            if stage not in stages:
                raise ValueError(f"Unknown documented stage: {stage} in {document}")
        for command in re.findall(
            r"\bseascape (?:--workspace (?:\"[^\"]+\"|\S+) )?(?:--debug )?([a-z][\w-]*)",
            text,
        ):
            if command not in commands:
                raise ValueError(f"Unknown documented command: {command} in {document}")
        for operation, family in re.findall(
            r"^seascape .*\b(download|inspect) ([a-z][\w-]*)", text, re.M
        ):
            if family not in (
                DOWNLOAD_FAMILIES if operation == "download" else FAMILIES
            ):
                raise ValueError(f"Unknown {operation} family: {family} in {document}")


def check_templates(root: Path) -> None:
    for relative in (
        "common.yaml",
        "data/project.yaml",
        "data/environment_seascape.yaml",
        "data/presentation_settings.yaml",
    ):
        if (root / "config" / relative).read_bytes() != (
            root / "src/seascape/resources/config" / relative
        ).read_bytes():
            raise ValueError(f"Packaged configuration drift: {relative}")


def generated_region(text: str, start: str, end: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"Expected one generated marker pair: {start}")
    return start + text.split(start, 1)[1].split(end, 1)[0] + end


def render_stage_inputs() -> str:
    """Render existing preflight declarations in a disposable initialized workspace."""
    with tempfile.TemporaryDirectory(prefix="seascape-docs-") as directory:
        workspace = Path(directory).resolve()
        previous = {
            key: os.environ.get(key)
            for key in (
                "SEASCAPE_WORKSPACE",
                "SEASCAPE_COMMON_CONFIG",
                "SEASCAPE_CANDIDATE_ROOT",
            )
        }
        try:
            os.environ["SEASCAPE_WORKSPACE"] = str(workspace)
            os.environ.pop("SEASCAPE_COMMON_CONFIG", None)
            os.environ.pop("SEASCAPE_CANDIDATE_ROOT", None)
            initialize_workspace(workspace)
            report = preflight_build(
                config_path="config/data/project.yaml",
                candidate_root=workspace / ".seascape/docs-preview",
                check_inputs=True,
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        lines = [
            STAGE_START,
            "| Stage | Direct dependencies | Configured local prerequisites (R=required, O=optional) |",
            "| --- | --- | --- |",
        ]
        for stage in report["stages"]:
            inputs = []
            for check in report["checks"]:
                if check["stage"] != stage["name"] or not check["path"]:
                    continue
                path = Path(check["path"])
                if not path.is_relative_to(workspace):
                    raise ValueError(
                        f"Default prerequisite outside disposable workspace: {check['name']}"
                    )
                inputs.append(
                    f"{'R' if check['required'] else 'O'}: {check['name']} — `{path.relative_to(workspace)}`"
                )
            cells = (
                f"`{stage['name']}`",
                ", ".join(f"`{x}`" for x in stage["dependencies"]) or "—",
                "<br>".join(dict.fromkeys(inputs))
                or "Existing dependency outputs / stage validation",
            )
            lines.append(
                "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"
            )
        optional_stages = [stage for stage in DOMAIN_LAYER_STAGES if stage.optional]
        for stage in optional_stages:
            dependencies = ", ".join(f"`{name}`" for name in stage.dependencies) or "—"
            lines.append(
                f"| `{stage.name}` | {dependencies} | Selected only; set its explicit source registry "
                "and bounds in `config/data/environment_seascape.yaml`, then run read-only preflight. |"
            )
        if len(report["stages"]) + len(optional_stages) != len(stage_names()):
            raise ValueError("Stage input reference lost workflow stages")
        return "\n".join([*lines, STAGE_END])


def check(root: Path, *, write_stage_reference: bool = False) -> dict:
    documents = [
        root / "README.md",
        *sorted((root / "docs").rglob("*.md")),
        root / "notebooks/README.md",
    ]
    for path in sorted((root / "src/seascape").rglob("*.md")):
        if "resources" not in path.parts:
            documents.append(path)
    check_templates(root)
    product_document = (root / "docs/products.md").read_text()
    catalog = yaml.safe_load((root / "config/feature_catalog.yaml").read_text())
    if generated_region(
        product_document, START_MARKER, END_MARKER
    ) != render_product_index(catalog):
        raise ValueError(
            "Reference product index differs from its checked-in catalog; do not regenerate against an empty workspace"
        )
    stage_path = root / "docs/stage-inputs.md"
    stage_text = stage_path.read_text()
    current = generated_region(stage_text, STAGE_START, STAGE_END)
    expected = render_stage_inputs()
    if write_stage_reference:
        stage_path.write_text(stage_text.replace(current, expected))
    elif current != expected:
        raise ValueError(
            "Stage input reference drift; review then use --write-stage-reference"
        )
    for name in ("install", "demo"):
        fenced_example((root / "README.md").read_text(), f"QUICKSTART {name}")
    fenced_example((root / "docs/WORKFLOWS.md").read_text(), "QUICKSTART plan")
    fenced_example((root / "docs/API.md").read_text(), "CONSUMER EXAMPLE", "python")
    check_commands(documents)
    return {
        "status": "PASS",
        "documents": len(documents),
        "local_links": check_links(root, documents),
        "workflow_stages": len(stage_names()),
        "external_urls": "not_checked (offline)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--write-stage-reference", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            check(
                args.root.resolve(), write_stage_reference=args.write_stage_reference
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
