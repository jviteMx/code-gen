"""Tests for the coding tool executor."""

import json
import tempfile
from pathlib import Path

import pytest

from code_agent.coder.tool_executor import CodingToolExecutor


@pytest.fixture
def ex(tmp_path):
    return CodingToolExecutor(str(tmp_path))


def _run(ex, tool, **args):
    return json.loads(ex.execute(tool, args))


def test_write_then_read(ex):
    r = _run(ex, "write_file", path="a.py", content="x = 1\ny = 2\n")
    assert r["written"] and r["created"]
    r = _run(ex, "read_file", path="a.py")
    assert "x = 1" in r["content"] and r["total_lines"] == 2


def test_edit_exact_unique(ex):
    _run(ex, "write_file", path="a.py", content="x = 1\n")
    r = _run(ex, "edit_file", path="a.py", old_string="x = 1", new_string="x = 42")
    assert r["edited"] and r["match"] == "exact"


def test_edit_ambiguous_requires_replace_all(ex):
    _run(ex, "write_file", path="a.py", content="a\na\na\n")
    r = _run(ex, "edit_file", path="a.py", old_string="a", new_string="b")
    assert "error" in r  # ambiguous
    r = _run(ex, "edit_file", path="a.py", old_string="a", new_string="b", replace_all=True)
    assert r["replacements"] == 3


def test_edit_whitespace_tolerant(ex):
    _run(ex, "write_file", path="a.py", content="def f():\n    return 1\n")
    # old_string has trailing spaces the file lacks; should still match
    r = _run(ex, "edit_file", path="a.py", old_string="    return 1   ", new_string="    return 2")
    assert r["edited"] and r["match"] == "whitespace-tolerant"
    assert "return 2" in (ex._workdir / "a.py").read_text()


def test_edit_no_match_gives_hint(ex):
    _run(ex, "write_file", path="a.py", content="def hello():\n    pass\n")
    r = _run(ex, "edit_file", path="a.py", old_string="def helo():", new_string="x")
    assert "error" in r and "did_you_mean" in r


def test_path_escape_blocked(ex):
    r = _run(ex, "read_file", path="../../../etc/passwd")
    assert "error" in r and "escape" in r["error"].lower()


def test_path_escape_prefix_sibling(tmp_path):
    # A sibling dir sharing a name prefix must not be treated as inside.
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj-evil").mkdir()
    (tmp_path / "proj-evil" / "secret").write_text("nope")
    ex = CodingToolExecutor(str(tmp_path / "proj"))
    r = _run(ex, "read_file", path="../proj-evil/secret")
    assert "error" in r


def test_search_finds_match(ex):
    _run(ex, "write_file", path="a.py", content="def target():\n    return 1\n")
    r = _run(ex, "search_files", pattern="target")
    assert r["count"] >= 1 and r["matches"][0]["file"] == "a.py"


def test_list_skips_junk_dirs(ex):
    _run(ex, "write_file", path="keep.py", content="1")
    (ex._workdir / "node_modules").mkdir()
    (ex._workdir / "node_modules" / "junk.js").write_text("1")
    r = _run(ex, "list_files")
    assert "keep.py" in r["entries"] and not any("node_modules" in e for e in r["entries"])


def test_edit_records_modified_only_on_success(ex):
    from code_agent.coder.session_memory import SessionMemory
    mem = SessionMemory(str(ex._workdir))
    ex._memory = mem
    _run(ex, "write_file", path="a.py", content="hello\n")
    mem.files_modified.clear()
    _run(ex, "edit_file", path="a.py", old_string="NOPE", new_string="x")  # fails
    assert mem.files_modified == []  # not recorded on failure
    _run(ex, "edit_file", path="a.py", old_string="hello", new_string="world")
    assert mem.files_modified == ["a.py"]
