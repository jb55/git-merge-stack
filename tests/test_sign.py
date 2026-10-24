import sys

from test_replay import CARD_LINE, refs, run

FAKE_GPG = """\
import sys
open(sys.argv[0] + ".log", "a").write("sign\\n")
sys.stdin.read()
sys.stderr.write("\\n[GNUPG:] SIG_CREATED D 1 8 00 0 FAKE\\n")
sys.stdout.write("-----BEGIN PGP SIGNATURE-----\\n\\nZmFrZQ==\\n-----END PGP SIGNATURE-----\\n")
"""


def signing(repo, tmp_path):
    """Turn on commit.gpgsign with a fake gpg that logs each call."""
    script = tmp_path / "gpg.py"
    script.write_text(FAKE_GPG)
    wrapper = tmp_path / "gpg"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    wrapper.chmod(0o755)
    repo.git("config", "commit.gpgsign", "true")
    repo.git("config", "gpg.program", str(wrapper))
    repo.git("config", "user.signingkey", "FAKE")
    return tmp_path / "gpg.py.log"


def signed(repo, rev) -> bool:
    return "\ngpgsig " in repo.git("cat-file", "commit", rev)


def test_restack_signs_what_it_writes(repo, shape, tmp_path, capsys):
    log = signing(repo, tmp_path)
    before = set(refs(repo).split())
    code, out, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 0, err
    new = repo.git("rev-list", "search", "filters", "api-search", "^origin/master").split()
    made = [c for c in new if c not in before and c not in {shape["x1"]}]
    assert made and all(signed(repo, c) for c in made)
    # api's x1 is reused as it was, unsigned in the fixture.
    assert repo.rev("api-search~2^1") == shape["x1"] and not signed(repo, shape["x1"])
    assert log.read_text().count("sign") == len(made)
    # The printed hashes are the signed ones.
    assert f"search: {shape['s2'][:12]} -> {repo.rev('search')[:12]}" in out
    assert repo.git("show", "api-search:evil") == "evil"


def test_dry_run_never_signs(repo, shape, tmp_path, capsys):
    log = signing(repo, tmp_path)
    code, _, err = run(repo, "restack", "-n", CARD_LINE, capsys=capsys)
    assert code == 1, err
    assert not log.exists()


def test_unsigned_without_gpgsign(repo, shape, capsys):
    code, _, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 0, err
    assert not signed(repo, "search")


def test_a_failing_signer_writes_nothing(repo, shape, tmp_path, capsys):
    signing(repo, tmp_path)
    repo.git("config", "gpg.program", "false")
    before = refs(repo)
    code, _, err = run(repo, "restack", CARD_LINE, capsys=capsys)
    assert code == 1
    assert "signing failed, so no ref was written" in err
    assert refs(repo) == before
