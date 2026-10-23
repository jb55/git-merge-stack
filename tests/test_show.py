import subprocess

import pytest

from conftest import SCRIPT
from git_merge_stack import Git, Graph, main


def test_card_shape(repo, shape, capsys):
    out, err = repo.show("--only", "search", "filters", "api-search", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search > filters ; api + search > api-search"
    assert err == ""


def test_hash_base_is_recorded(repo, shape, capsys):
    repo.show("--only", "search", capsys=capsys)
    assert repo.rev("refs/stack/base/search") == shape["m1"]


def test_no_record(repo, shape, capsys):
    repo.show("--no-record", capsys=capsys)
    assert repo.git("for-each-ref", "refs/stack/") == ""


def test_default_shows_every_branch_off_the_trunk(repo, shape, capsys):
    out, _ = repo.show(capsys=capsys)
    assert out == (
        f"{shape['m1'][:12]} > search > filters ; origin/master > api + search > api-search"
    )


STACK = "search > filters ; origin/master > api + search > api-search"


def unrelated(repo, shape):
    repo.checkout("-b", "lone", shape["m3"])
    repo.commit("u1")


def test_default_is_heads_stack(repo, shape, capsys):
    unrelated(repo, shape)
    repo.checkout("api-search")
    out, err = repo.show(capsys=capsys)
    assert out == f"{shape['m1'][:12]} > {STACK}"
    assert err == ""


def test_all_includes_unrelated_branches(repo, shape, capsys):
    unrelated(repo, shape)
    repo.checkout("api-search")
    out, err = repo.show("--all", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > {STACK} ; origin/master > lone"
    assert err == ""


def test_reaches_up_through_a_merge(repo, shape, capsys):
    # filters names only search; api-search is reached because it
    # merges search, and api, which nothing down there names, stays a name.
    unrelated(repo, shape)
    repo.checkout("filters")
    out, _ = repo.show(capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search > filters ; api + search > api-search"


def test_reaches_up_through_tilde(repo, shape, capsys):
    repo.checkout("-b", "side", shape["s1"])
    repo.commit("t1")
    out, _ = repo.show(capsys=capsys)
    assert "search~1 > side" in out and "api-search" in out


def test_only_printed_branches_are_recorded(repo, shape, capsys):
    repo.checkout("-b", "lone", shape["m1"])
    repo.commit("u1")
    repo.checkout("api-search")
    out, _ = repo.show(capsys=capsys)
    assert "lone" not in out
    assert repo.git("for-each-ref", "--format=%(refname)", "refs/stack/") == "refs/stack/base/search"


def test_fallback_on_master(repo, shape, capsys):
    unrelated(repo, shape)
    repo.checkout("master")
    out, err = repo.show(capsys=capsys)
    assert out == f"{shape['m1'][:12]} > {STACK} ; origin/master > lone"
    assert err == "note: master has no commits off origin/master; showing every branch off origin/master\n"


def test_fallback_when_detached(repo, shape, capsys):
    unrelated(repo, shape)
    repo.checkout("--detach", "api-search")
    out, err = repo.show(capsys=capsys)
    assert out.endswith("origin/master > lone")
    assert err == "note: HEAD is detached; showing every branch off origin/master\n"


def test_fallback_on_the_trunk(repo, shape, capsys):
    unrelated(repo, shape)
    repo.checkout("master")
    assert main(["-C", str(repo.path), "--trunk", "master", "show"]) == 0
    out, err = capsys.readouterr()
    assert "lone" in out
    assert err == "note: HEAD is on the trunk; showing every branch off master\n"


def test_own_commits_and_merge(repo, shape):
    g = Graph(Git(str(repo.path)))
    flow = g.derive("api-search")
    assert flow.own == [shape["l2"], shape["l1"], shape["M"]]
    assert flow.base == shape["x1"]
    assert g.derive("search").own == [shape["s2"], shape["s1"]]


def test_record_holds_the_fork_after_the_trunk_is_rewritten(repo, shape, capsys):
    repo.show(capsys=capsys)
    # Force-push a trunk that no longer contains m1: without the record,
    # search would own m0 and m1.
    repo.checkout("--orphan", "new-trunk")
    repo.git("rm", "-rfq", ".")
    repo.git("update-ref", "refs/remotes/origin/master", repo.commit("n0"))
    repo.checkout("api")
    repo.git("branch", "-D", "new-trunk", "master")
    out, _ = repo.show("--only", "search", "filters", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search > filters"


def test_branch_moved_on_after_the_merge(repo, shape, capsys):
    repo.checkout("search")
    repo.commit("s3")
    repo.commit("s4")
    out, _ = repo.show("--only", "search", "filters", "api-search", capsys=capsys)
    # filters now forks below search's tip, and the merge took an older search.
    assert out == (
        f"{shape['m1'][:12]} > search ; api + search~2 > api-search ; search~2 > filters"
    )


def test_base_gains_a_commit_after_the_merge(repo, shape, capsys):
    # api moves on after api-search merged on top of it: x1 is now a
    # fork whose longer arm, api-search's, starts with a merge. Merges sit
    # at the bottom, so x1 can only be api's, however long the other arm.
    repo.checkout("api")
    repo.commit("x2")
    out, err = repo.show("--only", "api", "api-search", capsys=capsys)
    assert out == "origin/master > api ; api~1 + search > api-search"
    assert err == ""


def test_equal_fork_warns(repo, shape, capsys):
    # search gains one commit after filters forked: two one-commit
    # arms from s2, and nothing in the graph says which branch owns s1-s2.
    # With no reflog to say which branch held s1-s2, the graph can't tell.
    repo.checkout("search")
    repo.commit("s3")
    repo.git("reflog", "expire", "--expire=now", "--all")
    out, err = repo.show("--only", "search", "filters", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > filters ; filters~1 > search"
    assert "filters and search fork equally" in err


def test_the_reflog_settles_an_equal_fork(repo, shape, capsys):
    # search's reflog has s2 as a tip; filters was only created there.
    repo.checkout("search")
    repo.commit("s3")
    out, err = repo.show("--only", "search", "filters", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search ; search~1 > filters"
    assert err == ""


def test_a_branch_grown_at_its_tip_keeps_a_longer_arm_off(repo, shape, capsys):
    # filters is two past s2, search one: the longer arm used to win s1-s2.
    repo.checkout("filters")
    repo.commit("f2")
    repo.checkout("search")
    repo.commit("s3")
    out, err = repo.show("--only", "search", "filters", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search ; search~1 > filters"


def test_cousin_side_branch(repo, shape, capsys):
    # A side branch forking below search's tip (the cousin that plain
    # --rebase-merges leaves behind) is stacked on search~N, so it moves too.
    repo.checkout("-b", "side", shape["s1"])
    repo.commit("t1")
    out, _ = repo.show("--only", "search", "side", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search ; search~1 > side"


def test_stacked_on_the_merged_branch(repo, shape, capsys):
    # A branch on api-search, which itself holds the merge.
    repo.checkout("-b", "on-flow", "api-search")
    repo.commit("o1")
    out, _ = repo.show("--only", "api-search", "on-flow", capsys=capsys)
    assert out == "api + search > api-search > on-flow"


def test_two_merges(repo, shape, capsys):
    repo.checkout("-b", "other", shape["m3"])
    repo.commit("o1")
    repo.checkout("-b", "both", "api")
    repo.merge("search", "merge search")
    repo.merge("other", "merge other")
    repo.commit("b1")
    out, _ = repo.show("--only", "both", capsys=capsys)
    assert out == "api + search + other > both"


def test_base_moved_on_upstream(repo, shape, capsys):
    # api is someone else's: only origin/api exists, and it has moved
    # on past the commit api-search merged into.
    repo.git("update-ref", "refs/remotes/origin/api", shape["x1"])
    repo.checkout("-b", "tmp", shape["x1"])
    repo.git("update-ref", "refs/remotes/origin/api", repo.commit("x2"))
    repo.checkout("master")
    repo.git("branch", "-D", "tmp", "api")
    out, err = repo.show("--only", "api-search", capsys=capsys)
    assert out == "origin/api~1 + search > api-search"
    assert err == ""


def test_commits_below_a_merge_warn(repo, shape, capsys):
    repo.checkout("-b", "mid", shape["m3"])
    below = repo.commit("below the merge")
    repo.merge("search", "merge search")
    repo.commit("above")
    out, err = repo.show("--only", "mid", capsys=capsys)
    assert out == f"{below[:12]} + search > mid"
    assert "commits below its merge" in err


def test_suffix_matching(repo, shape, capsys):
    repo.git("branch", "-m", "search", "feat/ui-12-index")
    out, _ = repo.show("--only", "index", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > feat/ui-12-index"


def test_ambiguous_suffix(repo, shape, capsys):
    repo.git("branch", "ui-search", "api-search")
    assert main(["-C", str(repo.path), "show", "--only", "i-search"]) == 1
    assert "matches several branches: api-search, ui-search" in capsys.readouterr().err


def test_script_runs_as_a_command(repo, shape):
    """The file itself, shebang and all, is the command you copy onto PATH."""
    p = subprocess.run(
        [str(SCRIPT), "-C", str(repo.path), "show", "--no-record", "--only", "search", "filters", "api-search"],
        capture_output=True, text=True, check=True,
    )
    assert p.stdout.strip() == f"{shape['m1'][:12]} > search > filters ; api + search > api-search"


def test_named_branch_expands_to_its_stack(repo, shape, capsys):
    unrelated(repo, shape)
    out, err = repo.show("filters", "api-search", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > {STACK}"
    assert err == ""


def test_only_prints_just_the_named_branches(repo, shape, capsys):
    out, _ = repo.show("--only", "api-search", capsys=capsys)
    assert out == "api + search > api-search"


def test_only_needs_branches(repo, shape, capsys):
    with pytest.raises(SystemExit):
        main(["-C", str(repo.path), "show", "--only"])


def test_merged_outsider_prints_as_a_name(repo, shape, capsys):
    # review merges other, which is off the trunk on its own; other is a
    # fixed point in review's term, and its own chain is not printed.
    repo.checkout("-b", "other", shape["m3"])
    repo.commit("o1")
    repo.checkout("-b", "review", "api-search")
    repo.merge("other", "merge other")
    repo.commit("r1")
    out, _ = repo.show("api-search", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > {STACK} + other > review"
    out, _ = repo.show("other", capsys=capsys)
    assert out == "origin/master > other ; api-search + other > review"


def test_a_branch_at_a_past_commit(repo, shape, capsys):
    # search gains s3; search@{1} is search before that, s2.
    before, _ = repo.show("--only", "search", "filters", capsys=capsys)
    repo.checkout("search")
    repo.commit("s3")
    records = repo.git("for-each-ref", "refs/stack/base/")
    out, err = repo.show("--only", "search@{1}", "filters", capsys=capsys)
    assert out == before
    assert f"note: search is shown at {shape['s2'][:12]}, not at its tip" in err
    assert repo.git("for-each-ref", "refs/stack/base/") == records  # a past state records nothing
    out, _ = repo.show("--only", "search~1", "filters", capsys=capsys)
    assert out == before


def test_a_branch_at_its_own_tip_is_just_the_branch(repo, shape, capsys):
    out, err = repo.show("--only", "search@{0}", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search"
    assert "note:" not in err


def test_a_revision_that_names_nothing(repo, shape, capsys):
    assert main(["-C", str(repo.path), "show", "search@{99}"]) == 1
    assert "'search@{99}' names no commit" in capsys.readouterr().err
