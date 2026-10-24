import io
import re
import subprocess

import pytest

from test_replay import CARD_LINE, conflicting, run
from test_scratch import stopped_worktree
from test_sign import signed, signing

REF = "refs/merge-stacks/s"


def saved(repo, ref=REF) -> str:
    return repo.git("cat-file", "blob", f"{ref}:stack")


def history(repo, ref=REF) -> list[str]:
    return repo.git("log", "--format=%s", ref).splitlines()


def restacked(repo, shape, capsys):
    """The shape restacked to CARD_LINE, so the graph matches it."""
    code, _, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 0, err


# -- save and list ---------------------------------------------------------


def test_save_commits_the_line_as_one_file(repo, shape, capsys):
    code, out, err = run(repo, "save", "s", CARD_LINE, capsys=capsys)
    assert code == 0, err
    tip = repo.rev(REF)
    assert out == f"saved s at {tip[:12]}\n"
    assert repo.git("ls-tree", "--name-only", REF) == "stack"
    assert saved(repo) == CARD_LINE
    assert history(repo) == ["save s"]
    # git's own DWIM finds it, so `git log merge-stacks/s` works.
    assert repo.rev("merge-stacks/s") == tip


def test_saving_again_advances_only_on_a_change(repo, shape, capsys):
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    first = repo.rev(REF)
    code, out, _ = run(repo, "save", "s", CARD_LINE, capsys=capsys)
    assert code == 0 and out == "s is unchanged\n"
    assert repo.rev(REF) == first
    run(repo, "save", "s", "origin/master > search", "-m", "just search", capsys=capsys)
    assert repo.rev(f"{REF}~1") == first
    assert history(repo) == ["just search", "save s"]
    assert saved(repo) == "origin/master > search"


def test_save_keeps_a_file_as_written(repo, shape, tmp_path, capsys):
    text = "# the card's stack\norigin/master > search > filters\napi + search > api-search\n"
    (tmp_path / "line").write_text(text)
    code, _, err = run(repo, "save", "s", str(tmp_path / "line"), capsys=capsys)
    assert code == 0, err
    assert saved(repo) + "\n" == text


def test_save_reads_stdin(repo, shape, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("origin/master > search\n"))
    code, _, err = run(repo, "save", "s", "-", capsys=capsys)
    assert code == 0, err
    assert saved(repo) == "origin/master > search"


def test_save_with_no_line_takes_heads_stack(repo, shape, capsys):
    repo.checkout("filters")
    code, _, err = run(repo, "save", "s", capsys=capsys)
    assert code == 0, err
    line, _ = repo.show("--line", capsys=capsys)
    assert saved(repo) == line.replace(" ; ", "\n")


def test_save_refuses_ranges_bad_lines_and_bad_names(repo, shape, capsys):
    for args, why in [
        (("s", f"origin/master > search:{shape['s1']}^..{shape['s2']}"), "a range is a one-off edit"),
        (("s", "origin/master > > search"), "empty ref"),
        (("a..b", CARD_LINE), "not a valid stack name"),
    ]:
        code, _, err = run(repo, "save", *args, capsys=capsys)
        assert code == 1 and why in err
    assert repo.git("for-each-ref", "refs/merge-stacks/") == ""


def test_save_signs_with_gpgsign(repo, shape, tmp_path, capsys):
    log = signing(repo, tmp_path)
    code, _, err = run(repo, "save", "s", CARD_LINE, capsys=capsys)
    assert code == 0, err
    assert signed(repo, REF)
    assert log.read_text().count("sign") == 1


def test_list_prints_names_tips_and_lines(repo, shape, tmp_path, capsys):
    (tmp_path / "line").write_text("origin/master > search\nsearch > filters\n")
    run(repo, "save", "search-only", str(tmp_path / "line"), capsys=capsys)
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    code, out, _ = run(repo, "list", capsys=capsys)
    assert code == 0
    assert out.splitlines() == [
        f"s            {repo.rev(REF)[:12]}  {CARD_LINE}",
        f"search-only  {repo.rev('refs/merge-stacks/search-only')[:12]}  origin/master > search ; search > filters",
    ]


def test_saved_stacks_are_not_pushed_by_default(repo, shape, tmp_path, capsys):
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "remote")], check=True)
    repo.git("push", "-q", "--all", str(tmp_path / "remote"))
    repo.git("push", "-q", "--tags", str(tmp_path / "remote"))
    assert repo.git("-C", str(tmp_path / "remote"), "for-each-ref", "refs/merge-stacks/") == ""
    # Saved stacks aren't stack branches either.
    assert repo.show("--all", "--line", capsys=capsys)[0].count("merge-stacks") == 0


# -- restack -n: drift ----------------------------------------------------


def dry(repo, capsys, *args) -> tuple[int, list[str]]:
    """restack -n's exit code, and the differences it lists before the preview."""
    code, out, _ = run(repo, "restack", "-n", *args, capsys=capsys)
    head, _, rest = out.partition("the graph differs from the line:\n")
    lines = []
    for l in rest.splitlines() if head != out else []:
        if not l.startswith("  "):
            break
        lines.append(l[2:])
    return code, lines


def test_dry_run_in_sync_with_a_saved_stack(repo, shape, capsys):
    restacked(repo, shape, capsys)
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    code, out, err = run(repo, "restack", "-n", "--stack", "s", capsys=capsys)
    assert code == 0, err
    assert out == "nothing moves\nin sync: the graph matches the line\n"


def test_drift_compares_commits_not_text(repo, shape, tmp_path, capsys):
    restacked(repo, shape, capsys)
    # Other spacing, a chain per line, and a branch by suffix all name the same graph.
    (tmp_path / "line").write_text("origin/master>search>filters\n\napi+search\n> api-search\n")
    run(repo, "save", "s", str(tmp_path / "line"), capsys=capsys)
    assert dry(repo, capsys, "--stack", "s") == (0, [])
    run(repo, "save", "s", "origin/master > search > ilters ; api + search > api-search", capsys=capsys)
    assert dry(repo, capsys, "--stack", "s") == (0, [])


def test_drift_when_the_trunk_moves(repo, shape, capsys):
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    code, out, _ = run(repo, "restack", "-n", "--stack", "s", capsys=capsys)
    assert code == 1
    assert out.startswith(
        "the graph differs from the line:\n"
        f"  search: the line has origin/master, the graph has {shape['m1'][:12]}\n"
        "search: "
    )


def test_drift_finds_a_merge_the_graph_lacks(repo, shape, capsys):
    restacked(repo, shape, capsys)
    line = "origin/master > search > filters ; api + search + filters > api-search"
    assert dry(repo, capsys, line) == (1, ["api-search: the line has api + search + filters, the graph has api + search"])


def test_drift_finds_a_chain_the_graph_lost(repo, shape, capsys):
    restacked(repo, shape, capsys)
    repo.git("branch", "-D", "filters")
    code, out, err = run(repo, "restack", "-n", CARD_LINE, capsys=capsys)
    assert code == 1
    assert "filters: no such branch; the line stacks it on search" in out + err
    # A branch with no commits left off the trunk has nothing stacked on search.
    repo.git("branch", "filters", shape["m2"])
    _, lines = dry(repo, capsys, CARD_LINE)
    assert "filters: has no commits off origin/master; the line stacks it on search" in lines


def test_drift_finds_a_chain_the_line_lacks(repo, shape, capsys):
    restacked(repo, shape, capsys)
    line = "origin/master > search ; api + search > api-search"
    assert dry(repo, capsys, line) == (1, ["filters: sits on search in the graph, but the line leaves it out"])


def test_drift_ignores_what_sits_on_a_fixed_point(repo, shape, capsys):
    # search is only read here, so filters on it isn't the line's business.
    restacked(repo, shape, capsys)
    assert dry(repo, capsys, "api + search > api-search") == (0, [])


def test_dry_run_an_unknown_stack(repo, shape, capsys):
    code, _, err = run(repo, "restack", "-n", "--stack", "nope", capsys=capsys)
    assert code == 1 and "no saved stack 'nope'" in err


def test_dry_run_takes_a_saved_stack(repo, shape, capsys):
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    # The new hashes carry the time of the run, so compare without them.
    by_line = re.sub(r"-> [0-9a-f]{12}", "->", run(repo, "restack", "-n", CARD_LINE, capsys=capsys)[1])
    code, out, _ = run(repo, "restack", "-n", "--stack", "s", capsys=capsys)
    assert code == 1 and re.sub(r"-> [0-9a-f]{12}", "->", out) == by_line


def test_dry_run_takes_no_exec_or_continue(repo, shape, capsys):
    for args in (("-n", "--exec", "true", CARD_LINE), ("-n", "--continue")):
        with pytest.raises(SystemExit):
            run(repo, "restack", *args, capsys=capsys)
    assert "-n writes none" in capsys.readouterr().err


# -- restack --stack -------------------------------------------------------


def test_restack_a_saved_stack(repo, shape, capsys):
    run(repo, "save", "s", CARD_LINE, capsys=capsys)
    tip = repo.rev(REF)
    code, out, err = run(repo, "restack", "--stack", "s", capsys=capsys)
    assert code == 0, err
    assert repo.rev("search~2") == shape["m3"]
    # The line didn't change, so the ref doesn't advance.
    assert repo.rev(REF) == tip and "saved" not in out
    assert dry(repo, capsys, "--stack", "s") == (0, [])


def test_restack_saves_a_new_line_once_it_lands(repo, shape, capsys):
    run(repo, "save", "s", "origin/master > search > filters", capsys=capsys)
    code, out, err = run(repo, "restack", "--stack", "s", CARD_LINE, capsys=capsys)
    assert code == 0, err
    assert f"saved s at {repo.rev(REF)[:12]}" in out
    assert saved(repo) == CARD_LINE
    assert history(repo) == ["restack s", "save s"]


def test_restack_creates_a_stack(repo, shape, capsys):
    code, _, err = run(repo, "restack", "--stack", "s", CARD_LINE, capsys=capsys)
    assert code == 0, err
    assert saved(repo) == CARD_LINE and history(repo) == ["restack s"]


def test_restack_saves_a_named_range_as_its_branch(repo, shape, capsys):
    line = f"origin/master > search:{shape['s2']}^..{shape['s2']} > filters ; api + search > api-search"
    code, _, err = run(repo, "restack", "--stack", "s", line, capsys=capsys)
    assert code == 0, err
    assert saved(repo) == "origin/master > search > filters\napi + search > api-search"
    assert dry(repo, capsys, "--stack", "s") == (0, [])


def test_restack_refuses_to_save_an_unnamed_range(repo, shape, capsys):
    line = f"origin/master > {shape['s1']}^..{shape['s2']} > filters"
    code, _, err = run(repo, "restack", "--stack", "s", line, capsys=capsys)
    assert code == 1 and "names no branch, so the line can't be saved" in err
    assert repo.rev("filters") == shape["f1"]


def test_restack_does_not_save_when_the_graph_still_drifts(repo, shape, capsys):
    # filters and api-search move along with search, but the line leaves them out.
    code, _, err = run(repo, "restack", "--stack", "s", "origin/master > search", capsys=capsys)
    assert code == 1
    assert repo.rev("search~2") == shape["m3"]
    assert "the graph doesn't match the line, so s was not saved" in err
    assert "filters: sits on search in the graph, but the line leaves it out" in err
    assert repo.git("for-each-ref", "refs/merge-stacks/") == ""


def test_a_stopped_restack_saves_on_continue(repo, shape, capsys):
    conflicting(repo, shape)
    code, _, err = run(repo, "restack", "--stack", "s", CARD_LINE, capsys=capsys)
    assert code == 1
    assert repo.git("for-each-ref", "refs/merge-stacks/") == ""
    wt = stopped_worktree(err)
    (repo.path / "s1").write_text("both\n")
    repo.git("-C", wt, "add", "s1")
    code, out, err = run(repo, "restack", "--continue", capsys=capsys)
    assert code == 0, err
    assert saved(repo) == CARD_LINE and "saved s" in out


def test_restack_continue_takes_no_stack(repo, shape, capsys):
    with pytest.raises(SystemExit):
        run(repo, "restack", "--continue", "--stack", "s", capsys=capsys)
    assert "a stopped restack keeps the one it started with" in capsys.readouterr().err
