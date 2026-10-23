import os
import subprocess

from git_merge_stack import main
from test_replay import CARD_LINE, conflicting, refs, run


def stopped_worktree(err: str) -> str:
    """Where the restack says it stopped."""
    return err.split("stopped at that commit in ", 1)[1].split(";", 1)[0]


def on(repo) -> str:
    return repo.git("symbolic-ref", "-q", "--short", "HEAD")


def git_in(repo, wt: str, *args: str) -> str:
    return repo.git("-C", wt, *args)


def test_conflict_resolved_in_the_worktree_lands(repo, shape, capsys):
    m4 = conflicting(repo, shape)
    before = refs(repo)
    code, _, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 1
    assert f"conflict: search: {shape['s1'][:12]} s1" in err
    assert refs(repo) == before
    wt = stopped_worktree(err)
    # It stops right here, detached at the new parent with git's own conflict state.
    assert wt == str(repo.path)
    assert git_in(repo, wt, "rev-parse", "HEAD") == m4
    assert "s1" in git_in(repo, wt, "diff", "--name-only", "--diff-filter=U")
    with open(os.path.join(wt, "s1"), "w") as f:
        f.write("both\n")
    git_in(repo, wt, "add", "s1")

    code, out, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 0, err
    assert repo.rev("search~2") == m4
    assert repo.git("show", "search~1:s1") == "both"
    assert repo.git("log", "-1", "--format=%s", "search~1") == "s1"
    assert repo.rev("filters~1") == repo.rev("search")
    assert repo.git("show", "api-search:s1") == "both"
    # And it's back on the branch it started on, clean.
    assert on(repo) == "master"
    assert repo.git("status", "--porcelain") == ""
    assert repo.git("worktree", "list").count("\n") == 0


def test_a_committed_resolution_and_a_second_stop(repo, shape, capsys):
    conflicting(repo, shape)
    m5 = repo.commit("m5", s2="master's s2")
    repo.git("update-ref", "refs/remotes/origin/master", m5)
    _, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    wt = stopped_worktree(err)
    with open(os.path.join(wt, "s1"), "w") as f:
        f.write("s1 resolved\n")
    git_in(repo, wt, "add", "s1")
    git_in(repo, wt, "commit", "-q", "-m", "whatever")
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 1
    assert f"conflict: search: {shape['s2'][:12]} s2" in err
    wt = stopped_worktree(err)
    with open(os.path.join(wt, "s2"), "w") as f:
        f.write("s2 resolved\n")
    git_in(repo, wt, "add", "s2")
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 0, err
    assert repo.rev("search~2") == m5
    assert repo.git("show", "search:s1") == "s1 resolved"
    assert repo.git("show", "search:s2") == "s2 resolved"
    # The message is the old commit's, not the one typed in the worktree.
    assert repo.git("log", "-1", "--format=%s", "search~1") == "s1"


def test_a_merge_conflict_is_re_merged_in_the_worktree(repo, shape, capsys):
    # master's m4 adds the file api's x1 adds, so re-merging search conflicts.
    repo.checkout("master")
    m4 = repo.commit("m4", x1="master's x1")
    repo.git("update-ref", "refs/remotes/origin/master", m4)
    code, _, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 1
    assert f"conflict: api-search: {shape['M'][:12]}" in err
    wt = stopped_worktree(err)
    assert git_in(repo, wt, "rev-parse", "HEAD") == shape["x1"]
    # The other parent is search as replayed, not yet written.
    assert git_in(repo, wt, "rev-parse", "MERGE_HEAD~2") == m4
    with open(os.path.join(wt, "x1"), "w") as f:
        f.write("x1 both\n")
    git_in(repo, wt, "add", "x1")
    # M was evil: the printed command carries what it added over a plain merge.
    carry = err.strip().splitlines()[-1].strip()
    assert carry.startswith("git diff ") and carry.endswith(" | git apply --3way")
    subprocess.run(carry, shell=True, cwd=wt, check=True, capture_output=True)
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 0, err
    assert repo.git("show", "api-search:evil") == "evil"
    merge = repo.rev("api-search~2")
    assert repo.git("rev-list", "--parents", "-n1", merge).split()[1:] == [shape["x1"], repo.rev("search")]
    assert repo.git("show", "api-search:x1") == "x1 both"
    assert repo.git("log", "-1", "--format=%s", merge) == "Merge branch 'search' into api-search"


def test_continue_refuses_unresolved_files(repo, shape, capsys):
    conflicting(repo, shape)
    run(repo, "restack", "origin/master > search", capsys=capsys)
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 1
    assert "unresolved files" in err


def test_abort_leaves_refs_untouched(repo, shape, capsys):
    m4 = conflicting(repo, shape)
    before = refs(repo)
    _, _, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    code, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert code == 1 and "--continue or --abort" in err
    code, out, _ = run(repo, "restack", "--abort", capsys=capsys)
    assert code == 0
    assert "no ref was written" in out
    assert refs(repo) == before
    assert on(repo) == "master" and repo.rev("HEAD") == m4
    assert repo.git("status", "--porcelain") == ""
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 1 and "no restack is stopped" in err


def test_continue_refuses_after_refs_move(repo, shape, capsys):
    conflicting(repo, shape)
    _, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    wt = stopped_worktree(err)
    with open(os.path.join(wt, "s1"), "w") as f:
        f.write("both\n")
    git_in(repo, wt, "add", "s1")
    repo.git("update-ref", "refs/heads/filters", shape["s2"])
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 1 and "refs moved" in err


def test_a_branch_being_moved_is_checked_out_again(repo, shape, capsys):
    conflicting(repo, shape)
    repo.checkout("search")
    _, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert repo.git("rev-parse", "--abbrev-ref", "HEAD") == "HEAD"  # detached at the conflict
    (repo.path / "s1").write_text("both\n")
    repo.git("add", "s1")
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 0, err
    assert on(repo) == "search"
    assert repo.rev("HEAD") == repo.rev("search") and repo.rev("search~2") == repo.rev("origin/master")
    assert (repo.path / "s1").read_text() == "both\n"
    assert repo.git("status", "--porcelain") == ""


def test_uncommitted_changes_refuse_to_stop(repo, shape, capsys):
    conflicting(repo, shape)
    (repo.path / "m0").write_text("local edit\n")
    before = refs(repo)
    code, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert code == 1
    assert "has uncommitted changes, so restack can't stop there" in err
    assert refs(repo) == before
    assert on(repo) == "master" and (repo.path / "m0").read_text() == "local edit\n"
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert "no restack is stopped" in err


def test_exec_runs_at_each_moved_tip(repo, shape, tmp_path, capfd):
    log = tmp_path / "log"
    code = main(["-C", str(repo.path), "restack", CARD_LINE, "--exec", f"git log -1 --format=%s >> {log}"])
    assert code == 0, capfd.readouterr().err
    assert sorted(log.read_text().split()) == ["f1", "l2", "s2"]
    assert repo.rev("search~2") == shape["m3"]
    assert repo.git("worktree", "list").count("\n") == 0


def test_failing_exec_writes_nothing(repo, shape, capfd):
    before = refs(repo)
    code = main(["-C", str(repo.path), "restack", CARD_LINE, "--exec", "test ! -e s2"])
    _, err = capfd.readouterr()
    assert code == 1
    assert "search: 'test ! -e s2' failed" in err and "no ref was written" in err
    assert refs(repo) == before
    assert repo.git("worktree", "list").count("\n") == 0
