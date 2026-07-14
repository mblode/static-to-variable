# Git history audit — licensed font binaries

**Date:** 2026-07-14 **Scope:** every commit on every ref (`--all`), every blob ever referenced. **Question:** has any licensed Circular donor, Glide source, or other font binary (`.otf` / `.ttf` / `.woff` / `.woff2` / `.glyphs` / `.ufo`) ever been committed to this repository's history — not just currently gitignored?

## Verdict

**CLEAN — safe to make public as-is.**

No font binary or font source file has ever been committed to any branch. The licensed Circular donors live only on the working tree under `cabinet/Circular/` (gitignored), and the Glide `.glyphs` sources are gitignored too. History contains only Python scripts, text/config, and the reconstruction reports.

## Commands run

```bash
# 1. Any commit touching donor / source / font paths, ever:
git log --all --oneline -- 'cabinet/Circular/**' '*.otf' '*.glyphs' '*.ttf'
#   -> (no output)

# 2. Every blob in every ref, filtered to font/source extensions:
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(rest)' \
  | grep -iE '\.(otf|ttf|woff2?|glyphs)$'
#   -> (no output)

# 3. All font/source formats anywhere in history:
git rev-list --objects --all | sed -E 's/^[0-9a-f]+ //' \
  | grep -iE '\.(otf|ttf|woff2?|glyphs|ufo|glyphspackage|designspace|dfont|pfb|pfa)($|/)'
#   -> (no output)

# 4. Every file extension ever committed under cabinet/:
git rev-list --objects --all | grep -iE '^[0-9a-f]{40} cabinet/' \
  | sed -E 's/^[0-9a-f]+ //' | grep -oiE '\.[a-z0-9]+$' | sort | uniq -c
#   ->  14 .py
#        1 .txt   (cabinet/requirements.txt)

# 5. Font binaries currently tracked:
git ls-files | grep -iE '\.(otf|ttf|woff2?|glyphs|ufo)$'
#   -> (none)
```

## Findings

- **Font binaries found in history: none.** Searches (2), (3), and (5) return nothing across all 496 objects in the object database.
- **`cabinet/` in history is source only.** The only paths ever committed under `cabinet/` are 14 `.py` build scripts and `cabinet/requirements.txt` — no `.otf`, no `.glyphs`, no `.ufo`.
- **Donors present on disk but never staged.** The Circular OTFs exist on the working tree (e.g. `cabinet/Circular/Circular/Circular-Regular.otf`); the entire `cabinet/Circular/` tree is gitignored and `git check-ignore` confirms each is ignored. They have never entered history.
- **Glide `.glyphs` sources are gitignored** (`glide-variable.glyphs`, `glide-variable-italic.glyphs`) and never committed.

## Consequence

No history rewrite (`git filter-repo`) and no fresh repo is required. The repository can be made public without exposing any licensed font binary.

Ongoing guard: keep the `cabinet/Circular/`, `*.glyphs`, `fonts/`, and `master_ufo/` entries in `.gitignore` so donors and sources stay out of future commits. Committed build outputs, if any are added later, should be Glide's own (fully reconstructed) fonts, not donors.
