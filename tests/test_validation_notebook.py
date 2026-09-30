"""Protect the portable notebook's source hygiene and truthful presentation gates.

Kernel/wheel acceptance uses scripts/check_validation_notebook.py with the notebook
extra; these lightweight tests also run in the ordinary runtime + test environment.
"""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

_NOTEBOOK = (
    Path(__file__).parents[1] / "notebooks/validation/01_TOOLKIT_VALIDATION.ipynb"
)


def _cells():
    return json.loads(_NOTEBOOK.read_text())["cells"]


def _tagged_source(tag):
    return next(
        "".join(cell["source"])
        for cell in _cells()
        if tag in cell.get("metadata", {}).get("tags", [])
    )


def test_source_is_unexecuted_and_delegates_processing_to_shared_demo():
    imports = []
    calls = []
    for cell in _cells():
        if cell["cell_type"] != "code":
            continue
        assert cell["execution_count"] is None
        assert cell["outputs"] == []
        tree = ast.parse("".join(cell["source"]))
        imports.extend(
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        calls.extend(
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
        assert not any(
            isinstance(node, ast.Attribute) and node.attr == "parents"
            for node in ast.walk(tree)
        )
    assert "seascape.demo" in imports
    assert calls.count("run_demo") == 1
    assert not set(calls) & {
        "run_pipeline",
        "build_bathymetry_parquet",
        "initialize_workspace",
    }


@pytest.mark.parametrize(
    "failure",
    ["false_check", "empty_checks", "failed_report", "report_mismatch", "environment"],
)
def test_notebook_rejects_failed_or_missing_evidence(failure):
    checks = {"known_constant_depth_m": True}
    report = {"status": "PASS", "checks": deepcopy(checks)}
    restored = True
    if failure == "false_check":
        checks["known_constant_depth_m"] = False
        report["checks"] = deepcopy(checks)
    elif failure == "empty_checks":
        checks.clear()
        report["checks"] = {}
    elif failure == "failed_report":
        report["status"] = "FAIL"
    elif failure == "report_mismatch":
        report["checks"] = {"different_check": True}
    else:
        restored = False
    namespace = {
        "pd": pd,
        "display": lambda value: None,
        "result": SimpleNamespace(checks=checks),
        "report": report,
        "ENVIRONMENT_RESTORED": restored,
    }
    with pytest.raises(AssertionError):
        exec(compile(_tagged_source("demo-checks"), str(_NOTEBOOK), "exec"), namespace)


def test_check_table_uses_real_results_and_summary_cannot_force_pass():
    shown = []
    namespace = {
        "pd": pd,
        "display": shown.append,
        "result": SimpleNamespace(checks={"known_constant_depth_m": True}),
        "report": {"status": "PASS", "checks": {"known_constant_depth_m": True}},
        "ENVIRONMENT_RESTORED": True,
    }
    exec(compile(_tagged_source("demo-checks"), str(_NOTEBOOK), "exec"), namespace)
    assert shown[0].to_dict("records") == [
        {"Check": "known_constant_depth_m", "Result": "PASS"},
        {"Check": "workspace_environment_restored", "Result": "PASS"},
    ]
    namespace["report"]["status"] = "FAIL"
    with pytest.raises(AssertionError, match="did not pass"):
        exec(compile(_tagged_source("demo-summary"), str(_NOTEBOOK), "exec"), namespace)
