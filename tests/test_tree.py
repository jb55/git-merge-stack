import pytest

import git_merge_stack
from git_merge_stack import main, shared_prefixes


def show(repo, *args, capsys):
    assert main(["-C", str(repo.path), "show", "--no-record", *args]) == 0
    return capsys.readouterr().out


@pytest.fixture
def on_tty(monkeypatch):
    monkeypatch.setattr(git_merge_stack, "tty", lambda: True)


def test_tree_of_heads_stack(repo, shape, capsys):
    repo.checkout("api-search")
    assert show(repo, "--tree", capsys=capsys) == (
        f"{shape['m1'][:12]}\n"
        "└─ search         2 commits\n"
        "   └─ filters     1 commit\n"
        "origin/master\n"
        "└─ api            1 commit\n"
        "   └─ api-search  3 commits  + search\n"
    )


def test_card_names_dim_their_shared_prefixes(repo, shape, capsys, on_tty):
    for old, new in [
        ("search", "feat/ui-12-index"),
        ("filters", "feat/ui-12-ranking"),
        ("api", "feat/web-api"),
        ("api-search", "feat/web-search"),
    ]:
        repo.git("branch", "-m", old, new)
    repo.checkout("-b", "feat/web-search-fixes", "feat/web-search")
    repo.merge("feat/ui-12-ranking", "merge filters")
    repo.commit("z1")
    out = show(repo, capsys=capsys).replace("\033[2m", "«").replace("\033[22m", "»")
    assert out == (
        f"{shape['m1'][:12]}\n"
        "└─ «feat/ui-12-»index             2 commits\n"
        "   └─ «feat/ui-12-»ranking        1 commit\n"
        "origin/master\n"
        "└─ «feat/web-»api                 1 commit\n"
        "   └─ «feat/web-»search           3 commits  + «feat/ui-12-»index\n"
        "      └─ «feat/web-search-»fixes  2 commits  + «feat/ui-12-»ranking\n"
        "\n"
        f"{shape['m1'][:12]} > «feat/ui-12-»index > «feat/ui-12-»ranking"
        " ; origin/master > «feat/web-»api + «feat/ui-12-»index"
        " > «feat/web-»search + «feat/ui-12-»ranking > «feat/web-search-»fixes\n"
    )


def test_tilde_base_hangs_under_its_branch(repo, shape, capsys):
    repo.checkout("-b", "side", shape["s1"])
    repo.commit("t1")
    out = show(repo, "--tree", "--only", "search", "side", capsys=capsys)
    assert out == (
        f"{shape['m1'][:12]}\n"
        "└─ search   2 commits\n"
        "   └─ side  1 commit   on search~1\n"
    )


def test_base_outside_the_stack_is_a_root(repo, shape, capsys):
    # As in test_base_moved_on_upstream: only origin/api exists, moved on.
    repo.git("update-ref", "refs/remotes/origin/api", shape["x1"])
    repo.checkout("-b", "tmp", shape["x1"])
    repo.git("update-ref", "refs/remotes/origin/api", repo.commit("x2"))
    repo.checkout("master")
    repo.git("branch", "-D", "tmp", "api")
    out = show(repo, "--tree", "--only", "api-search", capsys=capsys)
    assert out == "origin/api~1\n└─ api-search  3 commits  + search\n"


def test_piped_default_is_the_plain_line(repo, shape, capsys):
    repo.git("branch", "-m", "search", "feat/a-search")
    repo.git("branch", "-m", "filters", "feat/a-fix")
    out = show(repo, "--only", "feat/a-search", "feat/a-fix", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > feat/a-search > feat/a-fix\n"


def test_tty_default_is_tree_then_line(repo, shape, capsys, on_tty):
    out = show(repo, "--only", "search", "filters", capsys=capsys)
    tree, line = out.split("\n\n")
    assert tree.startswith(shape["m1"][:12] + "\n└─ search")
    assert line == f"{shape['m1'][:12]} > search > filters\n"


def test_line_on_a_tty(repo, shape, capsys, on_tty):
    out = show(repo, "--line", "--only", "search", "filters", capsys=capsys)
    assert out == f"{shape['m1'][:12]} > search > filters\n"


def test_no_color(repo, shape, capsys, on_tty):
    repo.git("branch", "-m", "search", "feat/a-search")
    repo.git("branch", "-m", "filters", "feat/a-fix")
    assert "\033[2m" in show(repo, "--only", "feat/a-search", "feat/a-fix", capsys=capsys)
    out = show(repo, "--no-color", "--only", "feat/a-search", "feat/a-fix", capsys=capsys)
    assert "\033" not in out
    assert out.endswith(f"\n\n{shape['m1'][:12]} > feat/a-search > feat/a-fix\n")


def test_tree_and_line_exclude_each_other(repo, shape):
    with pytest.raises(SystemExit):
        main(["-C", str(repo.path), "show", "--tree", "--line"])


@pytest.mark.parametrize("names, want", [
    ({"feat/ui-12-a", "feat/ui-12-b", "main"}, {"feat/ui-12-a": "feat/ui-12-", "feat/ui-12-b": "feat/ui-12-"}),
    ({"foobar-x", "foobaz-y"}, {}),  # no word is split: they share no whole '-' segment
    ({"flow", "flow-fixes"}, {"flow-fixes": "flow-"}),  # a name and its cut is shared; never all of a name
    ({"api-search", "api-search-fixes"}, {"api-search": "api-", "api-search-fixes": "api-search-"}),
    ({"api", "api-search", "api-search-fixes"},
     {"api-search": "api-", "api-search-fixes": "api-search-"}),  # never all of a name
])
def test_shared_prefixes(names, want):
    assert shared_prefixes(names) == want
