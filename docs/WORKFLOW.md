# Git + Jujutsu (jj) Development Workflow

> Last updated: 2026-04-26

This project uses a hybrid **Git + Jujutsu (jj)** workflow to keep our fork clean and easy to upstream.  
**New to jj?** Think of it as Git with an undo button for *everything* and a commit graph that stays tidy automatically.

---

## Core Concept: Two Worlds, One Repo

```
upstream/master  ──────────────────────────────────────●  (original MDCx, never touched)
                                                        │
our dev stack                                           ●  feat: add skill column
                                                        │
                                                        ●  feat: fix reward interface  ← dev
                                                        │
                                                        @  (your working copy)
```

| Bookmark | Meaning |
| :--- | :--- |
| `master` | Mirrors `upstream/master` — 100% original code |
| `dev` | Tip of our fork — always rebased on top of `master` |
| `@` | Your current working copy (jj's version of HEAD) |

---

## One-Time Setup

```bash
# 1. Add the upstream remote (skip if already done)
git remote add upstream https://github.com/Hazard804/mdcx.git

# 2. Initialize jj on the existing git repo
jj git init --git-repo .

# 3. Point master at upstream so jj always knows the source of truth
jj git fetch --remote upstream
jj bookmark track master --remote upstream
```

---

## Daily Workflow

### Start a new task

```bash
jj new dev -m "feat: description of task"
jj bookmark set dev          # slide the dev pointer up to your new change
```

> **Why `jj bookmark set dev`?**  
> `dev` is just a label. After `jj new`, you are *above* it. Moving the label up means "dev now means this new work."

### Save your progress (no staging needed)

Unlike Git, jj tracks all file changes automatically. There is **no `git add`**. Just describe what you did:

```bash
jj describe -m "wip: adjusted column offsets"
```

To start a fresh change on top (like `git commit && git checkout -b next`):

```bash
jj new -m "next step description"
```

### Sync with upstream

```bash
jj git fetch --remote upstream          # pull new upstream commits
jj rebase -s dev -d master              # replay our stack on top of the new master
```

### Sharing with GitHub (Pushing)

Before your first push, you must tell `jj` to track your local bookmark:

```powershell
jj bookmark track dev --remote=origin   # do this once
jj git push --remote origin             # push your progress
```

> **Safety Note:** If you've already pushed and want to "clean up" your commits, use `jj restore` (see Troubleshooting) instead of `jj squash` to avoid "Immutable Commit" errors.

# Optional: keep your GitHub fork's master in sync too
jj git push --remote origin --bookmark master
```

> **Conflict during rebase?** jj marks the conflict in the file but lets you keep working.  
> Fix the file, then run `jj describe` (no extra command needed — jj auto-detects resolution).

### Undo anything

```bash
jj undo          # revert the last jj operation — works on rebases, squashes, everything
```

---

## Viewing the Stack (`jj log`)

`jj log` is the most important command. Run it often.

```
@  wvqtpowu user@host 2 minutes ago
│  feat: add compatibility column
○  qvnkszrt user@host 1 hour ago
│  feat: fix reward interface columns    ← dev
○  zxoulstr user@host 3 hours ago
│  (empty) (this is master)
◆  upstream/master
```

| Symbol | Meaning |
| :--- | :--- |
| `@` | Your working copy (uncommitted changes live here) |
| `○` | A committed change |
| `◆` | A remote bookmark (upstream/master) |

> **Reading the graph**: time flows *upward*. `upstream/master` is at the bottom, your latest work is at the top.

---

## Cleaning Up: `jj squash` and `jj split`

### Collapse many small changes into one

```bash
jj squash          # merge @ into its parent
```

Example — before squash:
```
@  rlmtpowu  wip: tweak offset again
○  qvnkszrt  wip: tweak offset
○  zxoulstr  feat: add skill column    ← dev
```
After `jj squash` (run twice):
```
@  zxoulstr  feat: add skill column    ← dev
```

### Separate code from planning files

```bash
jj split           # interactively choose which files go into a new child change
```

This opens a diff view. Select only the `.planning/` files → they become a separate change, leaving your code change clean for a PR.

---

## Creating Pull Requests

### Method A: GSD (recommended)

```bash
/gsd-pr-branch
```

GSD automatically filters `.planning/` files and creates a clean Git branch ready for GitHub.

### Method B: Manual push

```bash
# Find the Change ID of your target change in jj log (e.g. "qvnk")
jj git push --change qvnk --remote origin --branch feature-name
# Then open a PR on GitHub from 'feature-name' → upstream/master
```

> **What does `--change qvnk` push?**  
> It pushes the *cumulative* state at that point — master + everything below `qvnk` in the stack. Changes *above* `qvnk` are not included.

---

## Quick Reference

| Task | Command |
| :--- | :--- |
| See the stack | `jj log` |
| Start a new change | `jj new -m "message"` |
| Describe / rename current change | `jj describe -m "message"` |
| Merge current change into parent | `jj squash` |
| Split one change into two | `jj split` |
| Undo last operation | `jj undo` |
| Fetch upstream + rebase | `jj git fetch --remote upstream && jj rebase -s dev -d master` |
| Show what changed in a change | `jj diff --change CHANGE_ID` |
| Jump to a specific change | `jj edit CHANGE_ID` |

### 4. Noise in PR Diffs (Line Endings)
**Issue:** GitHub shows 200+ files changed even if you only edited 5.  
**Reason:** The upstream uses **LF** (Unix) but your local commit has **CRLF** (Windows).  
**Fix:** Do **not** commit a global renormalization. Instead, use the **Selective Restore** technique below to create a clean PR branch.

---

## Pro Tip: The "Selective Restore" (Clean PRs)

If your local `dev` branch gets "messy" (with line-ending noise or planning files), use this to create a perfect Pull Request:

```powershell
# 1. Start a fresh change from the original master
jj new master -m "feat: my clean logic changes"

# 2. Pick ONLY the files you actually wrote/edited from your messy dev branch
# This ignores all the line-ending noise in other files!
jj restore --from dev mdcx/crawlers/my_new_file.py mdcx/config/enums.py

# 3. Push this clean commit as your PR branch
jj bookmark set pr-feature-name -r "@"
jj git push --remote origin --bookmark pr-feature-name
```

---

## Windows Setup (Do this once)

To avoid line-ending headaches in the future, run these in your repo:
1. `git config core.autocrlf input`
2. Never commit a `.gitattributes` file unless the maintainers explicitly ask for it.

---

## Git Syncing: Troubleshooting Stuck Files

**Issue:** A file is visible in `jj log` but `git status` shows it as "untracked," or it's missing on GitHub after a push.  
**Fix:** Explicitly stage the file in Git and re-import:
```powershell
git add .gitattributes   # (or whichever file is stuck)
jj git import
```
This "forces" the two systems to agree on the file's state.

---

## Practical Examples for New Users

### Example 1: Making your first change

```bash
# Make sure dev is up to date
jj git fetch --remote upstream
jj rebase -s dev -d master

# Start your work
jj new dev -m "feat: show skill column in expedition UI"
jj bookmark set dev

# ... edit files in your editor ...

# Check what jj sees (no staging needed)
jj diff

# Rename the change with a better message
jj describe -m "feat: add skill column to expedition interface"

# Start the next task
jj new -m "feat: next thing"
jj bookmark set dev
```

---

### Example 2: Sequential milestones (Foundation → Walls)

```bash
# ── Milestone 1: Foundation ──────────────────────────────────
jj new dev -m "milestone 1: foundation"
jj bookmark set dev
# ... GSD runs, makes git commits, jj imports them automatically ...
jj log       # you'll see multiple small changes above dev
jj squash    # collapse GSD's micro-commits into one clean Foundation node

# ── Milestone 2: Walls ───────────────────────────────────────
jj new dev -m "milestone 2: walls"
jj bookmark set dev
```

Stack after both milestones:
```
@  ●  milestone 2: walls   ← dev
   │
   ●  milestone 1: foundation
   │
◆  upstream/master
```

---

### Example 3: Submit M1 as a PR while M2 is in progress

```bash
jj log
# Output shows:
#   @  ●  milestone 2: walls     ← dev
#      │
#      ○  qvnk  milestone 1: foundation
#      │
#   ◆  upstream/master

# Step 1: separate .planning files from code in M1
jj split qvnk
# In the interactive view, select only .planning/ files for the second change.
# Result:
#   ○  NEW_ID  milestone 1: planning files
#   ○  CODE_ID milestone 1: foundation (code only)

# Step 2: push just the code change to your fork
jj git push --change CODE_ID --remote origin --branch pr-foundation

# Step 3: open PR on GitHub: pr-foundation → upstream/master
```

---

### Example 4: Upstream released a new version (sync + rebase)

```bash
jj git fetch --remote upstream
jj log
# You'll see upstream/master moved ahead of your stack base.

jj rebase -s dev -d master
# jj replays your entire dev stack on top of the new master.
# If there are conflicts, fix the marked files, then:
jj describe   # (or jj new) — jj auto-detects that conflicts are resolved
```

---

## GSD + jj Compatibility Notes

| Situation | What happens |
| :--- | :--- |
| GSD makes a Git commit | jj imports it automatically — run `jj log` to see it |
| `/gsd-pr-branch` creates a branch | A new bookmark appears in `jj log` — safe to delete after PR merges (`jj bookmark delete branch-name`) |
| GSD commits mix code + `.planning/` | Use `jj split` to separate them before creating a PR |

---

## Managing `.planning/` Files

- Keep `.planning/` changes in their own jj change whenever possible.
- Use `jj split` to extract `.planning/` changes if they got mixed with code.
- Never include `.planning/` in PRs to the original repo — use Method A (GSD) or manually exclude them with `jj split`.
