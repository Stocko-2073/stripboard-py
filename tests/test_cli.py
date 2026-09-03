"""The `stripboard` console script."""

from __future__ import annotations

import subprocess
import sys

import pytest

from stripboard import __version__
from stripboard.cli import _title, main


def run(*argv, cwd):
    """Invoke the CLI in-process, with cwd switched, returning the exit code."""
    import os
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return main(list(argv))
    finally:
        os.chdir(old)


class TestNew:
    def test_scaffolds_a_runnable_board(self, tmp_path):
        assert run("new", "my-board", cwd=tmp_path) == 0
        target = tmp_path / "my_board.py"
        assert target.exists()

        # The scaffold must actually run and produce a PDF named after the file.
        proc = subprocess.run([sys.executable, "my_board.py"], cwd=tmp_path,
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert (tmp_path / "my_board.pdf").exists()

    def test_hyphens_become_underscores_consistently(self, tmp_path):
        run("new", "a-b-c", cwd=tmp_path)
        body = (tmp_path / "a_b_c.py").read_text()
        assert "name='a_b_c'" in body, "output stem must match the module name"
        assert "A B C" in body, "the title is the humanized name"

    def test_size_arguments_reach_the_template(self, tmp_path):
        run("new", "wide", "--width", "34", "--height", "P", cwd=tmp_path)
        body = (tmp_path / "wide.py").read_text()
        assert "width=34" in body
        assert "height='P'" in body

    def test_refuses_to_overwrite(self, tmp_path):
        assert run("new", "dup", cwd=tmp_path) == 0
        assert run("new", "dup", cwd=tmp_path) == 1

    @pytest.mark.parametrize("bad", ["bad name", "bad!", "with/slash", "dot.dot", ""])
    def test_rejects_names_that_are_not_identifiers(self, tmp_path, bad):
        assert run("new", bad, cwd=tmp_path) == 2

    def test_outdir_is_created(self, tmp_path):
        assert run("new", "deep", "-o", str(tmp_path / "a" / "b"), cwd=tmp_path) == 0
        assert (tmp_path / "a" / "b" / "deep.py").exists()


class TestBuild:
    def test_renders_a_board(self, tmp_path):
        run("new", "buildme", cwd=tmp_path)
        assert run("build", "buildme.py", cwd=tmp_path) == 0
        assert (tmp_path / "buildme.pdf").exists()

    def test_missing_file_is_an_error(self, tmp_path):
        assert run("build", "nope.py", cwd=tmp_path) == 2

    def test_propagates_a_failing_board(self, tmp_path):
        (tmp_path / "broken.py").write_text("raise SystemExit(3)\n")
        assert run("build", "broken.py", cwd=tmp_path) == 3


class TestWatch:
    def test_missing_file_is_an_error(self, tmp_path):
        assert run("watch", "nope.py", cwd=tmp_path) == 2


def test_version_flag_reports_the_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_subcommand_is_an_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


@pytest.mark.parametrize(("name", "expected"), [
    ("tapbot", "TAPBOT"),
    ("my-board", "MY BOARD"),
    ("my_board", "MY BOARD"),
    ("a-b_c", "A B C"),
    ("_edge_", "EDGE"),
])
def test_title_humanizes_the_name(name, expected):
    assert _title(name) == expected
