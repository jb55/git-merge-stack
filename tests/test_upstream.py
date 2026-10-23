import pytest

from git_merge_stack import main


def run(repo, *args, capsys) -> tuple[int, str, str]:
    code = main(["-C", str(repo.path), *args])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def stack(repo):
    """master m0 - m1, search s1 - s2 - s3 on m0; origin/master is m1 until a test lands more."""
    c = {"m0": repo.commit("m0")}
    repo.checkout("-b", "search")
    c["s1"] = repo.commit("s1", s1="s1")
    c["s2"] = repo.commit("s2", s2="s2")
    c["s3"] = repo.commit("s3", s3="s3")
    repo.checkout("master")
    c["m1"] = repo.commit("m1")
    return c


def land(repo, *commits):
    """Make master the upstream once `commits` sit on it."""
    for make in commits:
        make()
    repo.git("update-ref", "refs/remotes/origin/master", repo.rev("master"))


def test_patch_id(repo, stack, capsys):
    land(repo, lambda: repo.git("cherry-pick", stack["s2"]))
    code, out, err = run(repo, "plan", "origin/master > search", capsys=capsys)
    assert code == 0, err
    assert f"search: {stack['s2'][:12]} s2  (patch-id matches upstream)" in out
    s1, s3 = stack["s1"][:12], stack["s3"][:12]
    assert f"; origin/master > search:{s1}^..{s1},{s3}^..{s3}" in out
    assert "s1  (" not in out and "s3  (" not in out


def test_suggested_line_drops_it(repo, stack, capsys):
    land(repo, lambda: repo.git("cherry-pick", stack["s2"]))
    s1, s3 = stack["s1"][:12], stack["s3"][:12]
    code, out, err = run(repo, "restack", f"origin/master > search:{s1}^..{s1},{s3}^..{s3}", capsys=capsys)
    assert code == 0, err
    assert repo.git("log", "--format=%s", "origin/master..search").split() == ["s3", "s1"]
    assert "already upstream" not in out


def test_conflict_says_it_may_be_upstream(repo, stack, capsys):
    # s1 landed, then changed again upstream, so replaying s1 conflicts.
    def landed_and_changed():
        repo.git("cherry-pick", stack["s1"])
        repo.commit("s1 again", s1="s1, changed upstream")
    land(repo, landed_and_changed)
    code, _, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert code == 1
    assert "It may already be upstream (patch-id matches upstream)" in err
    run(repo, "restack", "--abort", capsys=capsys)


def test_range_diff(repo, stack, capsys):
    """A commit that landed changed: range-diff pairs it, the other checks can't."""
    body = "".join(f"line {i}\n" for i in range(30))
    repo.checkout("-b", "big", stack["m0"])
    (repo.path / "big").write_text(body)
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "add big")
    mine = repo.rev("HEAD")
    repo.checkout("master")
    def changed():
        (repo.path / "big").write_text(body + "one line more\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "add big, as it landed")
    land(repo, changed)
    _, out, _ = run(repo, "plan", "origin/master > big", capsys=capsys)
    assert f"big: {mine[:12]} add big  (range-diff pairs it with an upstream commit)" in out


def test_empty_replay(repo, stack, capsys, monkeypatch):
    monkeypatch.setattr("git_merge_stack.RANGE_DIFF_MAX", 0)
    def squashed():
        for name in ("s2", "m2"):
            (repo.path / name).write_text(name + "\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "a bigger change")
    land(repo, squashed)
    _, out, _ = run(repo, "plan", "origin/master > search", capsys=capsys)
    assert f"search: {stack['s2'][:12]} s2  (replays as an empty commit)" in out


def test_restack_suggests_with_new_hashes(repo, stack, capsys):
    land(repo, lambda: repo.git("cherry-pick", stack["s1"]))
    code, out, err = run(repo, "restack", "origin/master > search", capsys=capsys)
    assert code == 0, err
    s2 = repo.rev("search~1")[:12]
    assert f"; origin/master > search:{s2}^..{repo.rev('search')[:12]}" in out
    # Backups are stamped to the second; two restacks in one would collide.
    repo.git("update-ref", "-d", repo.git("for-each-ref", "--format=%(refname)", "refs/stack-backup/"))
    code, _, err = run(repo, "restack", out.split("add to the line:  ; ")[1].strip(), capsys=capsys)
    assert code == 0, err
    assert repo.git("log", "--format=%s", "origin/master..search").split() == ["s3", "s2"]


def test_all_upstream(repo, stack, capsys):
    land(repo, lambda: repo.git("cherry-pick", stack["s1"], stack["s2"], stack["s3"]))
    _, out, _ = run(repo, "plan", "origin/master > search", capsys=capsys)
    assert "every commit of search looks upstream" in out


def test_nothing_upstream(repo, shape, capsys):
    _, out, _ = run(repo, "plan", "origin/master > search > filters ; api + search > api-search", capsys=capsys)
    assert "upstream" not in out


def test_range_keeps_its_gaps(repo, stack, capsys):
    repo.checkout("search")
    s4 = repo.commit("s4", s4="s4")
    repo.checkout("master")
    land(repo, lambda: repo.git("cherry-pick", s4))
    s1, s3 = stack["s1"][:12], stack["s3"][:12]
    line = f"origin/master > search:{s1}^..{s1},{s3}^..{s4[:12]}"
    code, out, err = run(repo, "plan", line, capsys=capsys)
    assert code == 0, err
    assert f"search: {s4[:12]} s4  (patch-id matches upstream)" in out
    assert f"; origin/master > search:{s1}^..{s1},{s3}^..{s3}" in out
    code, _, err = run(repo, "restack", out.split("add to the line:  ; ")[1].strip(), capsys=capsys)
    assert code == 0, err
    assert repo.git("log", "--format=%s", "origin/master..search").split() == ["s3", "s1"]
