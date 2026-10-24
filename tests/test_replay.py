from git_merge_stack import main

CARD_LINE = "origin/master > search > filters ; api + search > api-search"


def run(repo, *args, capsys) -> tuple[int, str, str]:
    code = main(["-C", str(repo.path), *args])
    out, err = capsys.readouterr()
    return code, out, err


def refs(repo) -> str:
    return repo.git("for-each-ref", "--format=%(refname) %(objectname)")


def test_card_line(repo, shape, capsys):
    code, out, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 0, err
    m3 = shape["m3"]
    search = repo.rev("search")
    assert repo.rev("search~2") == m3
    assert repo.rev("filters~1") == search
    flow = repo.rev("api-search")
    merge = repo.rev("api-search~2")
    assert repo.git("rev-list", "--parents", "-n1", merge).split()[1:] == [shape["x1"], search]
    assert repo.git("show", f"{flow}:evil") == "evil"
    assert "carried the difference forward" in err
    # Authors and messages survive exactly.
    assert repo.git("log", "-1", "--format=%an %ae %at%n%B", "search") == repo.git(
        "log", "-1", "--format=%an %ae %at%n%B", shape["s2"]
    )
    assert repo.git("log", "-1", "--format=%s", merge) == "Merge branch 'search' into api-search"
    out, err = repo.show("--only", "search", "filters", "api-search", capsys=capsys)
    assert out == CARD_LINE
    assert err == ""


def test_untouched_branches_keep_their_commits(repo, shape, capsys):
    run(repo, "restack", CARD_LINE, capsys=capsys)
    assert repo.rev("api") == shape["x1"]
    assert repo.rev("master") == shape["m3"]


def test_backups_and_hash_map(repo, shape, capsys):
    code, out, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 0, err
    backups = repo.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/stack-backup/")
    got = {line.split()[0].rsplit("/", 1)[1]: line.split()[1] for line in backups.splitlines()}
    assert got == {"search": shape["s2"], "filters": shape["f1"], "api-search": shape["l2"]}
    assert f"  {shape['s1'][:12]} -> {repo.rev('search~1')[:12]}  s1" in out
    assert f"  {shape['l2'][:12]} -> {repo.rev('api-search')[:12]}  l2" in out


def test_record_is_dropped_once_a_ref_names_the_base(repo, shape, capsys):
    repo.show("--only", "search", capsys=capsys)
    assert repo.rev("refs/stack/base/search") == shape["m1"]
    run(repo, "restack", CARD_LINE, capsys=capsys)
    assert repo.git("for-each-ref", "refs/stack/base/") == ""


def test_hash_base_is_recorded(repo, shape, capsys):
    code, _, err = run(repo, "restack", f"{shape['m2'][:12]} > search", capsys=capsys)
    assert code == 0, err
    assert repo.rev("refs/stack/base/search") == shape["m2"]
    out, _ = repo.show("--only", "search", capsys=capsys)
    assert out == f"{shape['m2'][:12]} > search"


def test_plan_writes_nothing(repo, shape, capsys):
    before = refs(repo)
    code, out, err = run(repo, "plan", CARD_LINE, capsys=capsys)
    assert code == 0, err
    assert refs(repo) == before
    assert out.startswith("search: ")
    assert "api-search: " in out and "filters: " in out
    assert "carried the difference forward" in err


def test_plan_nothing_moves(repo, shape, capsys):
    out, _ = repo.show("--no-record", capsys=capsys)
    code, out, _ = run(repo, "plan", out, capsys=capsys)
    assert (code, out.strip()) == (0, "nothing moves")


def test_cousin_moves_with_search(repo, shape, capsys):
    repo.checkout("-b", "side", shape["s1"])
    repo.commit("t1")
    repo.checkout("master")
    code, _, err = run(repo, "restack", "origin/master > search ; search~1 > side", capsys=capsys)
    assert code == 0, err
    assert repo.rev("side~1") == repo.rev("search~1")
    assert repo.rev("search~2") == shape["m3"]


def conflicting(repo, shape):
    """master gains a commit that edits s1's file differently."""
    repo.checkout("master")
    m4 = repo.commit("m4", s1="master's s1")
    repo.git("update-ref", "refs/remotes/origin/master", m4)
    return m4


def test_plan_reports_conflicts_and_restack_writes_nothing(repo, shape, capsys):
    conflicting(repo, shape)
    code, out, _ = run(repo, "plan", "origin/master > search", capsys=capsys)
    assert code == 1
    assert f"conflict: search: {shape['s1'][:12]} s1: s1" in out
    before = refs(repo)
    code, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert code == 1
    assert "no ref was written" in err
    assert refs(repo) == before


def test_plan_continues_past_a_conflict(repo, shape, capsys):
    conflicting(repo, shape)
    code, out, _ = run(repo, "plan", CARD_LINE, capsys=capsys)
    assert code == 1
    # The conflict at s1 doesn't hide what else moves.
    assert "filters: " in out and "api-search: " in out


def test_other_worktree_branch_moves_with_its_files(repo, shape, tmp_path, capsys):
    wt = tmp_path / "wt"
    repo.git("worktree", "add", "-q", str(wt), "filters")
    code, out, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 0, err
    assert repo.rev("filters~1") == repo.rev("search")
    assert repo.git("-C", str(wt), "status", "--porcelain") == ""
    assert (wt / "m3").exists()
    assert "filters: " in out
    assert repo.rev(f"{out.split('backups: ')[1].split()[0]}filters") == shape["f1"]


def test_other_worktree_with_changes_in_the_way(repo, shape, tmp_path, capsys):
    # The new filters brings m3 in from the trunk; the worktree has its own m3.
    wt = tmp_path / "wt"
    repo.git("worktree", "add", "-q", str(wt), "filters")
    (wt / "m3").write_text("mine\n")
    code, out, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 1
    assert f"filters did NOT move: it's checked out in {wt}" in err
    assert repo.rev("filters") == shape["f1"]
    assert (wt / "m3").read_text() == "mine\n"
    assert "filters: " not in out
    assert repo.rev("search~2") == shape["m3"]  # the rest is written


def test_current_branch_moves_with_its_files(repo, shape, capsys):
    repo.checkout("search")
    code, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert code == 0, err
    assert repo.rev("search~2") == shape["m3"]
    assert (repo.path / "m3").exists()
    assert repo.git("status", "--porcelain") == ""


def test_refuses_to_drop_commits(repo, shape, capsys):
    before = refs(repo)
    code, _, err = run(repo, "restack", "origin/master > filters", capsys=capsys)
    assert code == 1
    assert "refusing" in err
    assert f"filters: {shape['s2'][:12]} s2" in err
    assert refs(repo) == before


def test_drops_a_commit_the_new_history_already_has(repo, shape, capsys):
    # fixes holds a copy of api's new commit under its
    # merge. Once api-search is on the new api, the copy loses nothing.
    repo.checkout("api")
    x2 = repo.commit("x2")
    repo.checkout("-b", "fixes", "api-search")
    repo.git("cherry-pick", x2)
    copy = repo.rev("HEAD")
    repo.merge("filters", "merge filters")
    line = "api + search > api-search ; api-search + filters > fixes"
    code, out, err = run(repo, "plan", line, capsys=capsys)
    assert code == 0, err
    assert f"dropped, their patch is already in the new history:\n  fixes: {copy[:12]} x2\n" in out
    code, out, err = run(repo, "restack", line, capsys=capsys)
    assert code == 0, err
    assert f"  fixes: {copy[:12]} x2\n" in out
    assert repo.git("rev-list", "--parents", "-n1", "fixes").split()[1:] == [
        repo.rev("api-search"), shape["f1"]
    ]


def test_refuses_before_stopping_at_a_conflict(repo, shape, capsys):
    # search conflicts at s1, and the line also drops s1-s2 from
    # filters: the refusal comes first, so there's nothing to resolve.
    conflicting(repo, shape)
    line = "origin/master > search ; origin/master > filters"
    code, out, _ = run(repo, "plan", line, capsys=capsys)
    assert code == 1
    assert f"restack would refuse: drops filters: {shape['s2'][:12]} s2" in out
    before = refs(repo)
    code, _, err = run(repo, "restack", line, capsys=capsys)
    assert code == 1
    assert "refusing" in err and "stopped" not in err
    assert refs(repo) == before
    code, _, err = run(repo, "restack", "--continue", capsys=capsys)
    assert "no restack is stopped" in err


def test_claim_at_an_equal_fork(repo, shape, capsys):
    # show reads s1-s2 as filters' (the arms tie); the line's search~1
    # gives them to search, so moving search carries filters along.
    repo.checkout("search")
    repo.commit("s3")
    repo.checkout("master")
    code, _, err = run(repo, "restack", "origin/master > search ; search~1 > filters", capsys=capsys)
    assert code == 0, err
    assert repo.rev("search~3") == shape["m3"]
    assert repo.rev("filters~1") == repo.rev("search~1")


def test_dropping_an_evil_merge_warns(repo, shape, capsys):
    code, _, err = run(repo, "plan", "api > api-search", capsys=capsys)
    assert "dropping merge" in err


def test_restack_names_moves_the_line_did_not_write(repo, shape, capsys):
    code, out, err = run(repo, "restack", f"{shape['m2'][:12]} > search", capsys=capsys)
    assert code == 0, err
    assert "moved, though the line didn't write them: api-search, filters" in out


def test_restack_of_a_whole_line_names_nothing_extra(repo, shape, capsys):
    line = f"{shape['m2'][:12]} > search > filters ; api + search > api-search"
    code, out, err = run(repo, "restack", line, capsys=capsys)
    assert code == 0, err
    assert "search:" in out and "didn't write" not in out


def test_line_from_a_file(repo, shape, tmp_path, monkeypatch, capsys):
    f = tmp_path / "stack"
    f.write_text("# the card's stack\norigin/master > search > filters\napi + search > api-search\n")
    code, out, err = run(repo, "plan", "-f", str(f), capsys=capsys)
    assert code == 0, err
    assert "search: " in out and "api-search: " in out
    code, out, err = run(repo, "restack", "-f", str(f), capsys=capsys)
    assert code == 0, err
    assert repo.rev("search~2") == shape["m3"]
    out, _ = repo.show("--only", "search", "filters", "api-search", capsys=capsys)
    assert out == CARD_LINE


def test_line_from_stdin(repo, shape, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("origin/master > search\n"))
    code, out, err = run(repo, "plan", "-f", "-", capsys=capsys)
    assert code == 0, err
    assert "search: " in out


def test_a_branch_grown_at_its_tip_keeps_its_commits(repo, shape, capsys):
    # filters is two commits past search's tip s2, then search gains
    # one. At the fork s2, filters' arm is longer, so show gives s1-s2
    # to it; the line's `search > filters` says they're search's.
    repo.checkout("filters")
    f2 = repo.commit("f2")
    repo.checkout("search")
    s3 = repo.commit("s3")
    line = "origin/master > search > filters ; api + search > api-search"
    code, out, err = run(repo, "plan", line, capsys=capsys)
    assert code == 0, out + err
    assert "would refuse" not in out
    code, out, err = run(repo, "restack", line, capsys=capsys)
    assert code == 0, err
    assert repo.git("log", "--format=%s", "origin/master..search").split() == ["s3", "s2", "s1"]
    assert repo.git("log", "--format=%s", "search..filters").split() == ["f2", "f1"]
    assert repo.rev("search~3") == shape["m3"]
    out, _ = repo.show("--only", "search", "filters", capsys=capsys)
    assert out == "origin/master > search > filters"


def test_drops_an_old_copy_the_branch_below_rewrote(repo, shape, capsys):
    # fixes sits on api's x1; then x1 is amended with new content, so the
    # old copy's patch matches nothing. api's reflog says it was api's.
    repo.checkout("-b", "fixes", "api")
    y1 = repo.commit("y1")
    repo.checkout("api")
    (repo.path / "x1").write_text("x1 amended\n")
    repo.git("commit", "-q", "-a", "--amend", "-m", "x1")
    line = "api > fixes"
    code, out, err = run(repo, "plan", line, capsys=capsys)
    assert code == 0, out + err
    assert (
        "dropped, old copies of commits the branch below has since rewritten:\n"
        f"  fixes: {shape['x1'][:12]} x1  (an old copy of api's)\n"
    ) in out
    code, out, err = run(repo, "restack", line, capsys=capsys)
    assert code == 0, err
    assert repo.rev("fixes~1") == repo.rev("api")
    assert repo.git("log", "-1", "--format=%s", "fixes") == "y1" and repo.rev("fixes") != y1


def test_a_commit_the_branch_below_never_held_is_still_refused(repo, shape, capsys):
    # search's commits under filters were never api's, so moving filters
    # onto api loses them from filters, fork point or not.
    code, out, _ = run(repo, "plan", "api > filters", capsys=capsys)
    assert code == 1
    assert f"restack would refuse: drops filters: {shape['s2'][:12]} s2" in out
    assert "old copies" not in out
