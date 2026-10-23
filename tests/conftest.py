import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

# The tool is one extensionless script; load it by path as `git_merge_stack`.
SCRIPT = Path(__file__).resolve().parent.parent / "git-merge-stack"
_loader = importlib.machinery.SourceFileLoader("git_merge_stack", str(SCRIPT))
_spec = importlib.util.spec_from_loader("git_merge_stack", _loader)
_module = importlib.util.module_from_spec(_spec)
sys.modules["git_merge_stack"] = _module
_loader.exec_module(_module)

from git_merge_stack import main  # noqa: E402


class Scratch:
    """A real repo in a tmp dir, with commits dated one minute apart."""

    def __init__(self, path):
        self.path = path
        self.clock = 1_700_000_000
        self.git("init", "-q", "-b", "master")

    def git(self, *args: str) -> str:
        self.clock += 60
        env = {"GIT_AUTHOR_DATE": f"{self.clock} +0000", "GIT_COMMITTER_DATE": f"{self.clock} +0000"}
        p = subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, check=True,
            env={**os.environ, **env},
        )
        return p.stdout.strip()

    def commit(self, msg: str, **files: str) -> str:
        for name, text in (files or {msg.replace(" ", "-"): msg}).items():
            (self.path / name).write_text(text + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.rev("HEAD")

    def merge(self, other: str, msg: str, **evil: str) -> str:
        """Merge `other` into HEAD, adding `evil` files the plain merge lacks."""
        self.git("merge", "-q", "--no-ff", "--no-commit", other)
        for name, text in evil.items():
            (self.path / name).write_text(text + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.rev("HEAD")

    def checkout(self, *args: str):
        self.git("checkout", "-q", *args)

    def rev(self, rev: str) -> str:
        return self.git("rev-parse", rev)

    def show(self, *args: str, capsys) -> tuple[str, str]:
        assert main(["-C", str(self.path), "show", *args]) == 0
        out, err = capsys.readouterr()
        return out.strip(), err


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (tmp_path / "gitconfig").write_text(
        "[user]\n\tname = Scratch\n\temail = scratch@example.com\n"
        "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = master\n"
    )


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "repo").mkdir()
    return Scratch(tmp_path / "repo")


@pytest.fixture
def shape(repo):
    """The api-search shape from the card.

        m0 - m1 - m2 - m3                 origin/master (master)
              \\          \\
               s1 - s2     x1             search, api
                    |\\       \\
                    | f1      M - l1 - l2 filters, api-search
                    \\________/
    M merges search into api and also edits a file (an evil merge).
    """
    c = {}
    c["m0"] = repo.commit("m0")
    c["m1"] = repo.commit("m1")
    repo.checkout("-b", "search")
    c["s1"] = repo.commit("s1")
    c["s2"] = repo.commit("s2")
    repo.checkout("-b", "filters")
    c["f1"] = repo.commit("f1")
    repo.checkout("master")
    c["m2"] = repo.commit("m2")
    c["m3"] = repo.commit("m3")
    repo.git("update-ref", "refs/remotes/origin/master", c["m3"])
    repo.checkout("-b", "api")
    c["x1"] = repo.commit("x1")
    repo.checkout("-b", "api-search")
    c["M"] = repo.merge("search", "Merge branch 'search' into api-search", evil="evil")
    c["l1"] = repo.commit("l1")
    c["l2"] = repo.commit("l2")
    repo.checkout("master")
    return c
