"""Documentation drift and runnable public-consumer examples, without acquisition."""

from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture
def docs(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import check_docs

    return check_docs


def test_repository_documentation_matches_production_metadata(docs):
    report = docs.check(ROOT)
    assert report["status"] == "PASS"
    from seascape.workflow import stage_names

    assert report["workflow_stages"] == len(stage_names())
    assert report["local_links"] > 100


@pytest.mark.parametrize(
    "target", ["missing.md", "other.md#missing-heading", "../outside.md"]
)
def test_broken_local_links_fail(docs, tmp_path, target):
    document = tmp_path / "README.md"
    document.write_text(f"# Guide\n[reference]({target})\n")
    (tmp_path / "other.md").write_text("# Existing heading\n")
    with pytest.raises(ValueError, match="Broken (local|heading) link"):
        docs.check_links(tmp_path, [document])


def test_anchors_ignore_code_and_number_repeated_headings(docs, tmp_path):
    text = '# Guide\n## Same title\n## Same title\n```sh\n# Fake heading\n```\n<a id="explicit"></a>\n'
    assert docs.anchors(text) == {"guide", "same-title", "same-title-1", "explicit"}
    document = tmp_path / "README.md"
    document.write_text(
        text + "[reference](#same-title-1)\n[external](https://example.invalid/)\n"
    )
    assert docs.check_links(tmp_path, [document]) == 1


def test_configuration_template_drift_fails(docs, tmp_path):
    for relative in (
        "common.yaml",
        "data/project.yaml",
        "data/environment_seascape.yaml",
        "data/presentation_settings.yaml",
    ):
        for parent in ("config", "src/seascape/resources/config"):
            path = tmp_path / parent / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("same")
    docs.check_templates(tmp_path)
    (tmp_path / "config/common.yaml").write_text("drift")
    with pytest.raises(ValueError, match="Packaged configuration drift"):
        docs.check_templates(tmp_path)


@pytest.mark.parametrize(
    "command",
    [
        "seascape launch",
        "seascape build --only seascape-missing",
        "seascape download nonexistent",
    ],
)
def test_unknown_cli_commands_fail(docs, tmp_path, command):
    document = tmp_path / "guide.md"
    document.write_text(f"# Guide\n```sh\n{command}\n```\n")
    with pytest.raises(ValueError, match="Unknown"):
        docs.check_commands([document])


def test_missing_example_and_unsafe_quickstart_fail(docs):
    from check_quickstart import examples

    with pytest.raises(ValueError, match="marker pair"):
        docs.fenced_example("# Guide", "QUICKSTART demo")
    with pytest.raises(ValueError, match="review safety"):
        examples(
            (ROOT / "README.md")
            .read_text()
            .replace(
                '"$SEASCAPE_WORKSPACE" demo',
                '"$SEASCAPE_WORKSPACE" download bathymetry',
            ),
            (ROOT / "docs/WORKFLOWS.md").read_text(),
        )


def test_generated_product_drift_fails_before_workspace_generation(docs, monkeypatch):
    monkeypatch.setattr(docs, "render_product_index", lambda _: "drift")
    with pytest.raises(ValueError, match="Reference product index differs"):
        docs.check(ROOT)


@pytest.mark.parametrize(
    "name,kind", [("../escape", "file"), ("/absolute", "file"), ("pkg/link", "symlink")]
)
def test_source_archive_refuses_traversal_and_links(docs, tmp_path, name, kind):
    from check_quickstart import extract_source

    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as source:
        member = tarfile.TarInfo(name)
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "../../escape"
            source.addfile(member)
        else:
            member.size = 1
            source.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="Unsafe source archive"):
        extract_source(archive, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_quickstart_refuses_existing_or_checkout_output(docs, tmp_path):
    from check_quickstart import run

    existing = tmp_path / "existing"
    existing.mkdir()
    for output in (existing, ROOT / "forbidden-output"):
        with pytest.raises(ValueError, match="fresh and outside"):
            run(tmp_path / "not-read.tar.gz", ROOT, ROOT, output)


def test_consumer_example_reads_exact_retained_product_and_preserves_null_zero(
    docs, tmp_path, monkeypatch
):
    from seascape.core.artifacts import checksum_path
    from seascape.release import publish_candidate_release

    # Reuse the existing publisher-boundary fixture. Its audit flag is a fixture,
    # not regional scientific certification; no source or release gate is relaxed.
    spec = importlib.util.spec_from_file_location(
        "product_fixture", ROOT / "tests/test_products.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    candidate, workspace = tmp_path / "candidate", tmp_path / "workspace"
    path = fixture._candidate_fixture(candidate, b"")
    pq.write_table(
        pa.table(
            {"H3_INDEX": ["86283082fffffff", "862830877ffffff"], "depth_m": [0.0, None]}
        ),
        path,
    )
    before = checksum_path(path)
    publish_candidate_release(
        canonical_project_root=workspace, candidate_project_root=candidate
    )
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(workspace))
    example = docs.fenced_example(
        (ROOT / "docs/API.md").read_text(), "CONSUMER EXAMPLE", "python"
    )
    namespace = {}
    exec(compile(example, "docs/API.md:consumer-example", "exec"), namespace)
    artifact = namespace["artifact"]
    assert artifact.release_id == namespace["release_id"]
    assert artifact.resolution == 6
    assert artifact.path.is_relative_to(
        workspace / ".seascape/releases" / artifact.release_id
    )
    assert namespace["table"].to_pydict()["depth_m"] == [0.0, None]
    assert checksum_path(artifact.path) == before
