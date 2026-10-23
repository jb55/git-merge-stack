import shlex
import sys

import pytest

from test_replay import refs, run


def editor(monkeypatch, tmp_path, text: str | None):
    """Point GIT_EDITOR at a script that keeps what it was shown in `seen`,
    then saves `text` (None leaves the file as it was)."""
    seen = tmp_path / "seen"
    (tmp_path / "saved").write_text(text or "")
    script = tmp_path / "edit.py"
    script.write_text(
        "import shutil, sys\n"
        f"shutil.copy(sys.argv[1], {str(seen)!r})\n"
        + (f"shutil.copy({str(tmp_path / 'saved')!r}, sys.argv[1])\n" if text is not None else "")
    )
    monkeypatch.setenv("GIT_EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")
    return seen


def cx_cli_moved_on(repo):
    # api gains a commit after api-search merged on it.
    repo.checkout("api")
    repo.commit("x2")
    repo.checkout("api-search")


def test_base_moved_on(repo, shape, capsys):
    cx_cli_moved_on(repo)
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    m1 = shape["m1"][:12]
    line = f"{m1} > search > filters ; origin/master > api + search > api-search"
    assert f"refreshed: api~1 -> api\nline: {line}\n" in out
    assert "api-search: " in out
    assert repo.git("rev-list", "--parents", "-n1", "api-search~2").split()[1:] == [
        repo.rev("api"), shape["s2"]
    ]
    assert repo.rev("search") == shape["s2"]
    out, err = repo.show("--line", capsys=capsys)
    assert out == line


def test_merge_is_refreshed(repo, shape, capsys):
    repo.checkout("search")
    repo.commit("s3")
    repo.commit("s4")
    repo.checkout("api-search")
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    # filters sat on s2 too, so it is refreshed alongside the merge.
    assert "refreshed: + search~2 -> + search, search~2 -> search\n" in out
    assert repo.rev("api-search~2^2") == repo.rev("search")
    assert repo.rev("filters~1") == repo.rev("search")


def test_equal_fork_warns(repo, shape, capsys):
    # search and filters fork equally at s2, so `filters~1 >
    # search` is a tie-break, and refreshing it puts f1 under search.
    repo.checkout("search")
    repo.commit("s3")
    repo.git("reflog", "expire", "--expire=now", "--all")  # no history to settle it
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    assert "search: goes onto filters's tip, but they fork equally" in err
    assert repo.rev("search~1") == repo.rev("filters")


def test_a_branch_grown_at_its_tip_stays_below_its_sibling(repo, shape, capsys):
    # The longer arm used to win s1-s2, and plain restack then put search
    # on top of filters. The reflog keeps them search's.
    repo.checkout("filters")
    repo.commit("f2")
    repo.checkout("search")
    repo.commit("s3")
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    assert "refreshed: + search~1 -> + search, search~1 -> search\n" in out
    assert repo.git("log", "--format=%s", "search..filters").split() == ["f2", "f1"]
    assert repo.git("log", "--format=%s", "origin/master..search").split()[:3] == ["s3", "s2", "s1"]


def test_cousin_side_branch_moves_to_the_tip(repo, shape, capsys):
    # A deliberate below-tip fork moves too: -i is how to keep one.
    repo.checkout("-b", "side", shape["s1"])
    repo.commit("t1")
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    assert "search~1 -> search" in out
    assert "fork equally" not in err  # search's reflog held s1, so it isn't a guess
    assert repo.rev("side~1") == shape["s2"]


def test_nothing_stale(repo, shape, capsys):
    repo.checkout("api-search")
    before = refs(repo)
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    assert out.startswith("nothing to refresh")
    assert refs(repo) == before


def test_hash_base_warns_and_stays(repo, shape, capsys):
    # h1 sits under fixes's merge, and only a hash names it.
    repo.checkout("-b", "fixes", shape["m3"])
    h1 = repo.commit("h1")
    repo.merge("filters", "merge filters")
    repo.commit("g1")
    before = refs(repo)
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 0, err
    assert f"fixes: sits on {h1[:12]}, a commit of fixes with no name to refresh to" in err
    assert out.startswith("nothing to refresh")
    assert refs(repo) == before


def test_no_stack_at_head(repo, shape, capsys):
    code, out, err = run(repo, "restack", capsys=capsys)
    assert code == 1
    assert "master has no commits off origin/master" in err


def test_exec_runs_with_the_refreshed_line(repo, shape, capsys):
    cx_cli_moved_on(repo)
    code, out, err = run(repo, "restack", "--exec", "false", capsys=capsys)
    assert code == 1
    assert "'false' failed" in err


def test_interactive_runs_the_edit(repo, shape, monkeypatch, tmp_path, capsys):
    # Put the ~1 back on the base, keep the refreshed merge.
    cx_cli_moved_on(repo)
    m1 = shape["m1"][:12]
    seen = editor(monkeypatch, tmp_path, (
        "# a comment\n"
        f"{m1} > search > filters ;\n"
        "  api~1 + search > api-search\n"
        "# origin/master > nope\n"
    ))
    x1, flow = repo.rev("api~1"), repo.rev("api-search")
    code, out, err = run(repo, "restack", "-i", capsys=capsys)
    assert code == 0, err
    shown = seen.read_text()
    first, rest = shown.split("\n", 1)
    assert first == f"{m1} > search > filters ; origin/master > api + search > api-search"
    assert "# refreshed: api~1 -> api\n" in rest
    assert "\n# origin/master\n# └─ api " in rest  # the tree, drawn before the refresh
    assert "#    └─ api-search  3 commits  on api~1  + search\n" in rest
    assert all(s.startswith("#") for s in rest.splitlines() if s)
    assert f"line: {m1} > search > filters ; api~1 + search > api-search" in out
    # Nothing moved under it, so nothing is rewritten.
    assert repo.rev("api-search") == flow
    assert repo.rev("api-search~3") == x1


def test_interactive_edit_moves(repo, shape, monkeypatch, tmp_path, capsys):
    cx_cli_moved_on(repo)
    editor(monkeypatch, tmp_path, None)  # saved as shown: the refreshed line runs
    code, out, err = run(repo, "restack", "-i", capsys=capsys)
    assert code == 0, err
    assert repo.rev("api-search~2^1") == repo.rev("api")


def test_interactive_aborts(repo, shape, monkeypatch, tmp_path, capsys):
    cx_cli_moved_on(repo)
    m1 = shape["m1"][:12]
    unrefreshed = f"{m1}>search>filters ; origin/master>api ; api~1+search>api-search"
    before = refs(repo)
    for saved in ("", "# only comments\n\n", unrefreshed):
        editor(monkeypatch, tmp_path, saved)
        code, out, err = run(repo, "restack", "-i", capsys=capsys)
        assert code == 1
        assert "nothing to do; no ref was written" in err
        assert "line:" not in out
        assert refs(repo) == before


def test_interactive_nothing_stale_still_opens(repo, shape, monkeypatch, tmp_path, capsys):
    repo.checkout("api-search")
    seen = editor(monkeypatch, tmp_path, None)
    code, out, err = run(repo, "restack", "-i", capsys=capsys)
    assert code == 1
    assert "# nothing was refreshed" in seen.read_text()


@pytest.mark.parametrize("args", [["-i", "a > b"], ["--continue", "a > b"], ["--abort", "-i"]])
def test_bad_combinations(repo, args, capsys):
    with pytest.raises(SystemExit) as e:
        run(repo, "restack", *args, capsys=capsys)
    assert e.value.code == 2
