import pytest

from git_merge_stack import LineError, format_line, join_lines, parse, read, stack

CARD = "origin/master > search > filters ; api + search > api-search"


def test_plus_binds_tighter_than_stacking():
    assert parse(CARD) == [
        [("origin/master",), ("search",), ("filters",)],
        [("api", "search"), ("api-search",)],
    ]


def test_each_branch_sits_on_the_whole_term_before_it():
    assert stack(CARD) == {
        "search": ("origin/master",),
        "filters": ("search",),
        "api-search": ("api", "search"),
    }


def test_merges_mid_chain_belong_to_the_next_branch():
    assert stack("m > a + b + c > d") == {"a": ("m",), "d": ("a", "b", "c")}


def test_a_name_in_two_chains_is_one_branch():
    assert stack("m > a > b ; m > a > c") == {"a": ("m",), "b": ("a",), "c": ("a",)}


@pytest.mark.parametrize(
    "line, err",
    [
        ("", "empty chain"),
        ("m > a ;", "empty chain"),
        ("m > > a", "empty ref"),
        ("m + > a", "empty ref"),
        ("m a > b", "missing"),
        ("m", "stacks nothing"),
        ("m > a + b", "nothing stacked on it"),
        ("m > a ; n > a", "stacked on both"),
        ("m > a~1", "must be a branch"),
        ("a > b ; b > a", "cycle"),
        ("m > a ; a~1 > b ; b > c ; c + a > a2 ; a2 > a", "stacked on both"),
    ],
)
def test_rejects(line, err):
    with pytest.raises(LineError, match=err):
        stack(line)


def test_cycle_through_a_merge_is_rejected():
    with pytest.raises(LineError, match="cycle"):
        stack("m > a ; m + b > c ; c > b")


@pytest.mark.parametrize(
    "line",
    [
        CARD,
        "m > a + b > c ; m > b",
        "m > a ; a~1 > b",
        "m > a > b ; a > c",
    ],
)
def test_format_round_trips(line):
    assert stack(format_line(stack(line))) == stack(line)


def test_format_puts_merged_branches_first():
    # search is under both other branches, so its chain prints first.
    assert format_line(stack(CARD)) == CARD
    assert format_line(stack("api + search > api-search ; origin/master > search > filters")) == CARD


def test_ranges_are_terms():
    assert read("origin/master > a..b + br2 > lane") == (
        {"a..b": ("origin/master",), "lane": ("a..b", "br2")},
        {"a..b": [("a", "b")]},
    )


def test_named_range_binds_a_branch():
    assert read("api + search > flow:b3^..1a,c..d > top") == (
        {"flow": ("api", "search"), "top": ("flow",)},
        {"flow": [("b3^", "1a"), ("c", "d")]},
    )


@pytest.mark.parametrize(
    "line, err",
    [
        ("m > a...b > c", "no replay order"),
        ("m > a + x..y > c", "a merge takes one tip"),
        ("a..b > c", "no term below"),
        ("m > a..b", "nothing stacked on it"),
        ("m > x~1:a..b", "only a branch name"),
        ("m > x:a > c", "from..to"),
        ("m > x:a.. > c", "from..to"),
        ("m > x:a..b ; n > y > x:a..c", "two different ranges"),
    ],
)
def test_rejects_ranges(line, err):
    with pytest.raises(LineError, match=err):
        read(line)


def test_join_lines():
    text = """
    # the shape stack
    origin/master > search > filters
    origin/master > api + search
        > api-search

    api-search + filters > fixes ;
    a > b
    """
    assert join_lines(text) == (
        "origin/master > search > filters ; origin/master > api + search > api-search"
        " ; api-search + filters > fixes ; a > b"
    )
    assert join_lines("# nothing\n\n") == ""
