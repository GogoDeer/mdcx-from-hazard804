# Development Workflow

> Last updated: 2026-04-27

A pure-Git fork workflow for contributing to MDCx.

---

## Branches

```
upstream/master  ───────────────────●  (original MDCx, never touched)
                                     \
origin/master  ─────────────────────●  (your fork's mirror, always identical)
                                     \
origin/dev  ────────────────────────●  feat: javstash scraper
                                     │
                                     ●  docs: planning artifacts
                                     │
                                     ●  (your latest work)
```

| Branch | Purpose |
| :--- | :--- |
| `master` | Mirrors `upstream/master` — 100% original code |
| `dev` | Your full workspace — code, tests, `.planning/`, docs |
| `pr-*` | Temporary clean branches for Pull Requests (code only) |

---

## One-Time Setup

```powershell
# Add the upstream remote
git remote add upstream https://github.com/Hazard804/mdcx.git

# Ensure line endings are always LF (matches upstream)
git config core.autocrlf input
```

---

## Daily Workflow

### 1. Sync with upstream and rebase dev

```powershell
# Update master
git checkout master
git pull upstream master
git push origin master

# Rebase dev on top of the new master
git checkout dev
git rebase master
git push --force-with-lease origin dev
```

> **Why rebase?** Keeps `dev` as a clean linear stack on top of `master` —
> no merge commits. `--force-with-lease` is safe because only you use this fork.

### 2. Work on dev

```powershell
git checkout dev

# ... do your work ...

git add .
git commit -m "feat: implement javstash scraper"
git push --force-with-lease origin dev
```

> **Tip:** Commit everything together — code, tests, `.planning/`, docs.
> The separation happens only when you create a PR.

When a milestone is complete, **tag it** before starting the next one:

```powershell
git tag vM1    # snapshot of dev at the end of milestone 1
```

> **Why tag?** If M1 and M2 both modify `mdcx/config/enums.py`, you need a
> way to grab the M1-only version. The tag preserves that exact state.

### 3. Create a clean PR (code only)

When a feature is ready to submit upstream, use either method:

#### Method A: Manual cherry-pick (recommended for few files)

```powershell
# Start a clean branch from master
git checkout master
git checkout -b pr-feature-name

# Cherry-pick ONLY the files you want — from the milestone TAG
git checkout vM1 -- mdcx/crawlers/javstash.py
git checkout vM1 -- mdcx/config/enums.py
git checkout vM1 -- mdcx/config/models.py
git checkout vM1 -- mdcx/crawlers/__init__.py
git checkout vM1 -- tests/crawlers/test_javstash.py

# Commit and push
git commit -m "feat: implement JavStash GraphQL scraper"
git push origin pr-feature-name

# Go back to dev
git checkout dev
```

#### Method B: `/gsd-pr-branch` (better for many files)

```powershell
# Create a temporary branch from the milestone tag
git checkout -b temp-m1 vM1

# Let GSD auto-filter .planning/ commits
/gsd-pr-branch

# Remove non-.planning files that GSD doesn't filter
git checkout temp-m1-pr
git rm --cached docs/WORKFLOW.md .gitattributes 2>/dev/null
git commit --amend --no-edit

# Push and clean up
git push origin temp-m1-pr
git checkout dev
git branch -d temp-m1
```

> **Method A vs B:** Method A gives you exact control over every file.
> Method B is faster when a milestone touches many files, but you must
> manually remove `docs/WORKFLOW.md` and `.gitattributes` since GSD only
> auto-filters `.planning/`.

Then open a PR on GitHub: `pr-feature-name` (or `temp-m1-pr`) → `upstream/master`.

> **How to find the right files per milestone:**
> Check `.planning/milestones/vM1-ROADMAP.md` — each phase plan lists
> "Files to change/create". Or check the phase SUMMARY.md files for what
> was actually modified.

### 4. After PR is merged

```powershell
# Same as step 1: sync master and rebase dev
git checkout master
git pull upstream master
git push origin master

git checkout dev
git rebase master
git push --force-with-lease origin dev

# Clean up the PR branch
git branch -d pr-feature-name
git push origin --delete pr-feature-name
```

---

## Troubleshooting

### Line-ending noise in PR diffs

**Symptom:** GitHub shows hundreds of files changed even though you only edited a few.

**Cause:** Your local files have CRLF (Windows) but upstream expects LF (Unix).

**Fix:**
```powershell
# Ensure autocrlf is set (one-time)
git config core.autocrlf input

# If files are already wrong, renormalize:
git add --renormalize .
git commit -m "chore: normalize line endings"
```

### Accidentally committed .planning/ files to a PR branch

```powershell
git rm -r --cached .planning/
git rm --cached docs/WORKFLOW.md
git rm --cached .gitattributes
git commit -m "chore: remove non-upstream files from PR"
git push origin pr-feature-name
```

---

## Files That Should Never Be in a PR

These files exist in `dev` but must **never** appear in a PR to upstream:

- `.planning/` — GSD planning artifacts
- `docs/WORKFLOW.md` — this workflow document
- `.gitattributes` — local line-ending enforcement

When creating a PR branch, only `git checkout <tag> -- <file>` the specific
source code and test files you want to submit.
