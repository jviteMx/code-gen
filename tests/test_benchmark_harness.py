"""Focused unit tests for benchmark scoring and collection helpers."""

import subprocess

import pytest

from benchmark.harness.grade import count_pytest_tests, localization_precision
from benchmark.harness.metrics import overall, pass_at_k, per_task
from benchmark.harness.schema_check import find_schemathesis_cli, run_schemathesis


def test_count_pytest_tests_counts_collected_cases(monkeypatch, tmp_path):
    output = "\n".join([
        "suite/test_ui.py::test_plain",
        "suite/test_ui.py::test_parametrized[small]",
        "suite/test_ui.py::test_parametrized[large]",
        "3 tests collected in 0.01s",
    ])
    completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    assert count_pytest_tests("suite", tmp_path) == 3


def test_localization_is_precision_not_expected_file_recall():
    expected = {"app/a.py", "app/b.py"}
    assert localization_precision({"app/a.py"}, expected) == 1.0
    assert localization_precision({"app/a.py", "notes.txt"}, expected) == 0.5
    assert localization_precision(set(), expected) == 0.0


def test_pass_at_k_boundaries():
    assert pass_at_k(3, 0, 1) == 0.0
    assert pass_at_k(3, 3, 1) == 1.0
    assert pass_at_k(3, 1, 1) == pytest.approx(1 / 3)
    assert pass_at_k(3, 1, 3) == 1.0


def test_overall_statistics_are_clustered_by_task():
    trials = [
        {"task_id": "A", "level": 1, "score": 1.0, "resolved": True,
         "wall_s": 1.0, "requests": 1},
        {"task_id": "A", "level": 1, "score": 0.0, "resolved": False,
         "wall_s": 1.0, "requests": 1},
        {"task_id": "B", "level": 1, "score": 1.0, "resolved": True,
         "wall_s": 1.0, "requests": 1},
    ]

    stats = overall(per_task(trials))
    # Task A contributes its 0.5 mean once; task B contributes 1.0 once.
    assert stats["mean_score"] == 0.75
    assert stats["pass_at_1"] == 0.75


def test_schemathesis_cli_resolves_from_active_environment():
    path = find_schemathesis_cli()
    assert path is not None
    assert "schemathesis" in path.lower()


def test_schemathesis_run_is_scoped_to_task_paths(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("benchmark.harness.schema_check.find_schemathesis_cli",
                        lambda: "schemathesis")
    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, _ = run_schemathesis(
        "http://127.0.0.1:8000", tmp_path,
        include_paths=["/api/cards/{card_id}/move"],
    )

    assert ok is True
    assert captured["cmd"][-2:] == ["--include-path", "/api/cards/{card_id}/move"]
