# git-merge-stack

Rebase git stacks that contain merges, described by one line:

    origin/master > search > filters ; api + search > api-search

`show` derives the line from the graph. You edit a token, and `restack` makes
the graph match the line.

## Install

It is one Python file (3.11+, stdlib only) that shells out to git. Copy it
onto PATH and git runs it as a subcommand:

    cp git-merge-stack ~/bin/ && git merge-stack show

Use `git merge-stack -h` for usage. `git merge-stack --help` is caught by git
itself, which looks for a man page that doesn't exist.

Tests load that same file by path: `uv run --with pytest pytest -q`.

The project's landing page is `docs/index.html`, served at
https://jb55.github.io/git-merge-stack/.

MIT licensed; see `LICENSE`.

## The syntax

    line  := chain (';' chain)*
    chain := term ('>' term)*
    term  := (ref | range) ('+' ref)*
    range := [branch ':'] ref '..' ref (',' ref '..' ref)*

- `a > b`: b's own commits sit on a.
- `a + b`: merge b into a's tip. The branch after the next `>` starts from
  that merge, so the merge is that branch's bottom commit. `+` binds tighter
  than `>`, and `a + b + c` is two merges, left to right.
- `;` separates chains. A name in two chains is the same branch.
- A name never written after `>` is a fixed point: it is read and never
  rewritten.
- A ref is any git ref, hash or `ref~N`. On the command line a branch also
  matches by unique suffix (`index` finds `feat/ui-12-index`).
- `a..b` is a term only after `>`: those commits, replayed onto the term
  before it, with `+` merges and later terms building on its tip:
  `origin/master > a..b + br2 > lane`. Git refnames can't hold `..` or `:`,
  so a range never reads as a branch.
- `name:a..b` makes branch `name` exactly those commits on top of its term,
  dropping its other commits: `api + search > flow:b32e^..1a9a` keeps
  `flow`'s merge and its commits up to 1a9a. `name:a..b,c..d` keeps several
  runs, one after the other, and drops the gaps (interleaved fixups).
- Only `..`: `a...b` has no replay order and is refused. A range after `+`
  is refused too, since a merge takes one tip. A range is replayed as a
  graph: merges inside it keep their shape, and a first parent outside the
  range becomes the term below (rebase-cousins). `show` never prints ranges.

## show

    git merge-stack show [branch...] [--all | --only] [--tree | --line] [--no-color]
                         [--trunk REF] [--no-record]

A branch can carry a revision, `show X@{2}`, `show X@{yesterday}` or `show
X~1`, to see the stack as if X were at that commit, say before a restack. The
other branches stay at their tips, so commits only X's old self reached
print as hashes, and nothing is recorded under `refs/stack/base/`.

`show X` prints what a restack of X's line could move. Going down, that's X
and every branch its term names, recursively, through the base, `+` merges
and `~N`: the tokens you might edit. Going up from those, it's every branch
stacked on one of them, recursively: what moves when you edit one. A branch
up there that merges in something outside the set keeps it as a name in its
term, a fixed point, not a chain of its own. With no branches, X is the
branch you're on; with several, the sets are joined.

`--all` prints every branch off the trunk instead, and `--only` prints just
the named branches, e.g. to keep a stack branch as a fixed point in the line.
When HEAD is detached, on the trunk, or on a branch with no commits off it,
`show` prints everything and says why on stderr. Every branch is derived
either way; only what's printed changes.

On a terminal, `show` draws the stack as a tree, then prints the line under
it. Piped, as in `$(git merge-stack show)`, it prints only the line, with no
color, because that is what `restack` reads. `--tree` and `--line` pick one
form either way.

    ae4655a25e9c
    └─ feat/ui-12-index             2 commits
       └─ feat/ui-12-ranking        1 commit
    origin/master
    └─ feat/web-api                 1 commit
       └─ feat/web-search           3 commits  + feat/ui-12-index
          └─ feat/web-search-fixes  2 commits  + feat/ui-12-ranking

Each branch hangs under the branch its base names, or under the base itself
when that's the trunk, a hash or a ref outside the stack. A `~N` base hangs
under its branch with `on X~N` on the row, since it sits below the tip. `+`
merges are labels on the right. The count is the branch's own commits, its
merges included.

On a terminal, a name that shares a prefix with another name in the line, cut
at a `/` or `-`, has its longest such prefix dimmed (`feat/ui-12-`), in
both the tree and the line. The name is still printed whole, so it copies
whole. `--no-color` turns this off.

This command only reads, apart from one write: a fork point that only a hash
can name is recorded under `refs/stack/base/<branch>`.

Every commit not on the trunk is a stack commit. The trunk is `origin/HEAD`,
else `origin/main`, `origin/master`, `main`, `master`, or whatever `--trunk`
gives. A branch owns the stack commits on its first-parent chain down to the
first commit that something else claims:

- the tip of another ref: a local branch, a tag, or a remote branch that
  doesn't shadow a local one;
- a commit on the chain of a ref that forks from this branch, which is named
  `ref~N`;
- the base recorded for it, so the fork point survives the trunk being
  rewritten under it;
- the trunk. A trunk commit is named by a ref when one points at it, else by
  a hash.

Merges may only sit at the bottom of a branch, where they become the `+` refs
of its term. A commit below a merge is the branch's base. When that commit
has no name of its own, `show` warns that the commits under it read as the
base.

At a fork, two branches continue from one commit and neither is stacked on
the other. The commits below the fork belong to the branch whose reflog has a
tip at or above them on the shared chain: it held them before the other one
forked, so a branch grown at its tip keeps its commits. The entry that
created a branch doesn't count. Failing that, they go to the local branch
over the remote one, then to the branch with the longer arm. When the arms
tie, nothing says which branch owns them, so `show` picks one by name and
warns.

`plan` and `restack` don't depend on this guess: a line's `x > y` makes y's
commits that sit on x's own chain x's.

## plan and restack

    git merge-stack plan '<line>'
    git merge-stack restack '<line>'

Either takes `-f FILE` (`-` for stdin), or `--stack NAME` for a saved
stack (see [Saved stacks](#saved-stacks)), in place of the line. Each line of the
file is a chain; a line that ends with, or one that starts with, `>`, `+` or
`;` carries the chain on. Blank lines and `#` lines are dropped:

    # stack
    origin/master > feat/ui-12-index > feat/ui-12-ranking
    origin/master > feat/web-api + feat/ui-12-index > feat/web-search
    feat/web-search + feat/ui-12-ranking > feat/web-search-fixes

Both replay the stack in memory with `git merge-tree --write-tree
--merge-base=<old parent>` and `git commit-tree`, so no worktree is touched.
Authors, author dates and messages are kept exactly; the committer is you.
With `commit.gpgsign` set, `restack` signs every commit it writes, just
before writing the refs (`commit-tree -S`); `plan` and a stopped restack
never call gpg. Commits it reuses keep their own signatures.

- The stack is every branch off the trunk plus the line's branches. A branch
  the line writes takes the line's term; every other branch keeps the term
  `show` would print, so whatever sits above a moved branch moves with it.
- Each token is resolved against the old graph, then mapped: a stack branch
  named bare follows to its new tip, and `branch~N` or a hash goes through
  the old->new map. A commit is reused when its parent didn't change.
- `x~N` in the line makes x own its chain down to that commit. At an equal
  fork, where `show` gave the commits below it to the other branch, they move
  to x, and the other branch then sits on x~N.
- A merge is replayed as a plain merge of its new parents, old and new merges
  paired by position. When the old merge differs from a plain re-merge of its
  old parents (an evil merge, or a conflict resolution), the difference is
  carried forward as a three-way merge (base = the old plain merge, ours =
  the new plain merge, theirs = the old merge) with a warning. Dropping such
  a merge warns too.

`plan` writes no refs. It prints each moving branch with its old->new hashes
and titles, then every conflict with its files, continuing past them on
merge-tree's conflicted tree. It exits 1 when anything conflicts. Its new
hashes are a preview: the committer date differs on the real run.

`restack` refuses a line that would drop a commit from a moving branch's
history (moving a branch off the one it was stacked on drops that one's
commits from it), save the commits a `name:` range leaves out on purpose,
those whose patch the new history already holds (`git cherry`), and old
copies of commits the branch below has since amended or rebased, which it
lists as dropped. That last kind is found the way `git rebase --fork-point`
finds it: a branch the line stacks on local branch `y` has its commits at
or below `git merge-base --fork-point y` (read from y's reflog) left out of
the replay. It replays the whole line before deciding, so the refusal
comes before any conflict stop; `plan` prints it too. Then it stops at the
first conflict, before writing any ref. Otherwise it
writes one `git update-ref --stdin` transaction, guarded by the old values:

- each moved branch;
- its backup at `refs/stack-backup/<YYYY-MM-DD-HHMMSS>/<branch>`;
- `refs/stack/base/<branch>`, set when only a hash names the new base, else
  deleted.

After writing, `restack` lists each branch it moved that the line didn't
write, so a hand-trimmed line can't move something you didn't see.

A branch checked out in a worktree, this one or any other, moves with `git
-C <worktree> reset --keep <new>` after the transaction, so its files follow.
A worktree whose local changes are in the way refuses: that branch stays put,
with its backup written, and `restack` says so and exits 1. It ends with the
old->new hash map.

## restack with no line

    git merge-stack restack [-i] [--exec '<cmd>']

With no line, `restack` takes `show`'s line for HEAD's stack (the set plain
`show` prints) and refreshes it: every `X~N` that names a branch in it
becomes `X`, a base or a `+` merge alike, so every branch goes onto the
current tip of what it's stacked on. It prints what changed and the line it
runs, then restacks as usual:

    refreshed: api~1 -> api, + search~2 -> + search
    line: origin/master > api + search > api-search ; origin/master > search

A refreshed merge re-merges a newer branch, so it changes content. When
nothing is stale it says so and writes nothing. A base only a hash names has
no tip to refresh to, so it stays, with a warning. At an equal fork, which
branch `show` stacks on the other is a tie-break, so moving onto its tip
warns too.

`-i` opens the git editor on the refreshed line, with the unrefreshed one,
the tree and a short help below it as `#` comments. What's saved runs, `#`
lines dropped; it may span several lines. Saving it empty, or as the
unrefreshed line, aborts and writes nothing. That's how to keep a branch on
an older commit on purpose: put its `~N` back.

## Commits already upstream

`plan` and `restack` check each moving branch's regular (non-merge) commits
against what its new base brings in, merges included, and list the ones
that look upstream already:

- patch-id: `git cherry` finds the same diff upstream;
- range-diff: `git range-diff` pairs it with a changed upstream commit
  (tried only when at most 200 commits came in);
- empty: replayed onto the new base, it changes nothing.

These are suggestions. Nothing is dropped unless the line says so, so each
branch's list ends with the chain to add to the line that keeps the rest,
as a `name:` range:

    already upstream? (a suggestion; nothing is dropped unless the line says so)
      search: d858012dd386 s2  (patch-id matches upstream)
      to drop, add to the line:  ; origin/master > search:b178b133fa20^..b178b133fa20,227e949a1077^..227e949a1077

`plan` prints the old hashes; `restack` prints the ones it just wrote, so the
chain applies to the restacked branch. When `restack` stops at a conflict on
a commit that looks upstream, it says so.

## Conflicts

    git merge-stack restack '<line>' [--exec '<cmd>']
    git merge-stack restack --continue
    git merge-stack restack --abort

When `restack` hits a conflict, it stops right where you ran it, the way
`git rebase` does. That worktree must be clean (untracked files are fine).
It's detached at the replayed parent, and the step is redone there with
rerere on: `git cherry-pick --no-commit` for a commit, `git merge --no-ff
--no-commit` for a merge. The line and the resolutions so far are saved
under `$GIT_COMMON_DIR/stack-restack/`. No ref is written.

Resolve the files and `git add` them, or commit the resolution as one commit
on that parent, in the same place. Then `--continue` takes the tree, records it with rerere,
and replays the whole line again. It uses each resolved tree in place of
merge-tree's. The commit's own author and message are kept, not the
worktree commit's. The first run pins the commit date, so the rerun builds
the same commits up to the next conflict. `--continue` refuses when any
branch, remote or tag moved since the stop. When the restack finishes, or
`--abort` drops it, the worktree is put back on the branch it was on, so a
branch the restack moved is checked out at its new tip.

A merge is redone as a plain merge. When the old merge changed more than
that (an evil merge), the stop also prints the `git diff <plain> <old> | git
apply --3way` that carries the difference over.

`--exec <cmd>` runs `cmd` with the shell in a scratch worktree at each moved
branch's new tip, after the replay and before any ref is written. The first
failure stops the restack, and nothing is written.

## Saved stacks

    git merge-stack save <name> [<line> | FILE | -] [-m MSG]
    git merge-stack check <name>
    git merge-stack list
    git merge-stack plan --stack <name>
    git merge-stack restack --stack <name> [<line> | -f FILE | -i]

A stack can be saved by name, so the line lives in git instead of a loose
file. Each saved stack is a ref:

    refs/merge-stacks/<name>   a commit; its tree holds one file, `stack`

`stack` is the line as written, comments and line breaks kept. Each save
that changes it is a new commit on top of the last, so `git log -p
merge-stacks/<name>` is the history of the stack's shape. Saving the same
text again writes nothing. With `commit.gpgsign` set, the commit is signed
(`commit-tree -S`, since plain `commit-tree` ignores that config).

`save` takes a line (anything with a `>`), a FILE, or `-` for stdin. With
none, it saves `show`'s line for HEAD's stack, a chain per line. It refuses
a line with ranges: a range names commits to drop by hash, which is a
one-off edit, not a shape to keep.

`list` prints each saved stack's name, tip and line.

`check` compares the saved line with the graph and exits 1 on drift, so an
agent can run it as a gate after a restack. It compares commits, not text,
so spacing, line breaks and a branch named by suffix don't count. It
prints one line per difference:

    search: the line has origin/master, the graph has 1a2b3c4d5e6f
    filters: no such branch; the line stacks it on search
    filters: has no commits off origin/master; the line stacks it on search
    filters: sits on search in the graph, but the line leaves it out

A branch the line writes must sit on the commits its term names, with its
merges in that order. A branch the graph stacks on one of the line's
branches must be named in the line; what sits on a fixed point, which the
line only reads, is not its business.

`plan --stack <name>` plans the saved line. `restack --stack <name>`
restacks it, or the line given with it (a line, `-f FILE`, or `-i` on
HEAD's stack), and saves that line as `<name>` once the restack is done and
`check` passes. So the ref only advances when the graph matches the line.
A stopped restack saves when `--continue` finishes it. A `name:a..b` range
is saved as plain `name`, since after the restack that branch is those
commits; an unnamed range has no branch to keep, so `--stack` refuses it
up front.

Nothing under `refs/merge-stacks/` is pushed or fetched unless you ask:
`git push` only sends branches and tags by default. To share them:

    git push <remote> 'refs/merge-stacks/*:refs/merge-stacks/*'
