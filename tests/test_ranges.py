from test_replay import run


def subjects(repo, rev: str) -> list[str]:
    return repo.git("log", "--format=%s", rev).splitlines()


def test_named_range_drops_the_rest(repo, shape, capsys):
    # The api-search rework: keep the lane's first commit, drop the rest.
    l1 = shape["l1"][:12]
    line = f"origin/master > search ; api + search > api-search:{l1}^..{l1}"
    code, out, err = run(repo, "plan", line, capsys=capsys)
    assert code == 0, err
    code, out, err = run(repo, "restack", line, capsys=capsys)
    assert code == 0, err
    search = repo.rev("search")
    assert repo.rev("search~2") == shape["m3"]
    assert subjects(repo, "api-search")[:2] == ["l1", "Merge branch 'search' into api-search"]
    assert repo.git("rev-list", "--parents", "-n1", "api-search~1").split()[1:] == [shape["x1"], search]
    assert "l2" not in subjects(repo, "api-search")
    assert repo.git("show", "api-search:evil") == "evil"
    # filters still sat on the old search, so it moved with it.
    assert repo.rev("filters~1") == search


def test_runs_drop_the_gaps(repo, capsys):
    repo.commit("m0")
    repo.checkout("-b", "br")
    a, b, c, d = (repo.commit(x) for x in "abcd")
    repo.checkout("master")
    m1 = repo.commit("m1")
    code, _, err = run(repo, "restack", f"master > br:{a[:12]}^..{a[:12]},{b[:12]}..{c[:12]}", capsys=capsys)
    assert code == 0, err
    assert subjects(repo, "br") == ["c", "a", "m1", "m0"]
    assert repo.rev("br~2") == m1


def test_unnamed_range_under_a_merge(repo, capsys):
    m0 = repo.commit("m0")
    repo.checkout("-b", "other")
    o1 = repo.commit("o1")
    o2 = repo.commit("o2")
    repo.checkout("-b", "br2", m0)
    repo.commit("q1")
    repo.checkout("-b", "lane", m0)
    repo.commit("z1")
    repo.checkout("master")
    code, _, err = run(repo, "restack", "master > other~1..other + br2 > lane", capsys=capsys)
    assert code == 0, err
    assert subjects(repo, "lane~1^1") == ["o2", "m0"]
    assert repo.rev("lane~1^2") == repo.rev("br2")
    assert subjects(repo, "lane")[0] == "z1"
    # The range copies: other keeps its commits.
    assert repo.rev("other") == o2 and repo.rev("other~1") == o1


def test_merges_inside_a_range_keep_their_shape(repo, capsys):
    m0 = repo.commit("m0")
    repo.checkout("-b", "br")
    repo.commit("a")
    repo.checkout("-b", "side")
    repo.commit("s")
    repo.checkout("br")
    repo.commit("b")
    repo.merge("side", "merge side")
    repo.commit("c")
    repo.git("branch", "-D", "side")
    repo.checkout("master")
    m1 = repo.commit("m1")
    code, _, err = run(repo, "restack", f"master > br:{m0[:12]}..br", capsys=capsys)
    assert code == 0, err
    merge = repo.rev("br~1")
    p1, p2 = repo.git("rev-list", "--parents", "-n1", merge).split()[1:]
    assert subjects(repo, p1)[:3] == ["b", "a", "m1"]
    assert subjects(repo, p2)[:3] == ["s", "a", "m1"]
    assert repo.rev(f"{p1}~1") == repo.rev(f"{p2}~1")
    assert repo.rev(f"{p1}~2") == m1


def test_empty_range_is_refused(repo, shape, capsys):
    code, _, err = run(repo, "plan", "origin/master > search:search..search > filters", capsys=capsys)
    assert code == 1
    assert "holds no commits" in err
