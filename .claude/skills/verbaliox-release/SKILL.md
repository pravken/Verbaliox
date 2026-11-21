---
name: verbaliox-release
description: Release a Verbaliox version (a beta vX.Y.Z-beta.N or a release vX.Y.Z) — changelog, version, the PR to main, CI to green, the Release workflow with its tag, and the check of the published page and its signature. Use only when the user asks for a release in their own words; also for a build without a tag (it publishes nothing) to check the launcher and the installer.
---

# Verbaliox: a release

A release reaches every user through the updater: it is outward and cannot be taken back (old releases and
tags are never deleted). **Only when the user asks for it**, for the version they name (a beta or not).
A build without a tag is always allowed: it publishes nothing.

Never touch `RELEASE_PUBLIC_KEY` (app/updater.py) or ask for, create or keep `RELEASE_SIGNING_KEY`
(docs/release-signing.md). Never build or upload release files by hand: without the workflow's signature the
app will not install them.

## Betas first

New work goes out as `vX.Y.Z-beta.N` (a pre-release, only for «Получать бета-версии»); `vX.Y.Z` when the beta
was checked — or when the user says so («давай не бету»).

## Steps

1. **Everything green on the branch**: the whole test suite and compileall by exit code, the browser checks
   (`verbaliox-ui-check` skill: `check.sh`), the diff read through.
2. **CHANGELOG.md**: the section `## X.Y.Z — English` and `## X.Y.Z` (Russian), in the user's words, what they
   will notice first; fixes grouped. A beta takes the sections of its future version. Check the page text:
   `python tools/release_notes.py vX.Y.Z <out.md>` (the English section comes first; exit code 0).
3. **The version**: `__version__` in `app/__init__.py` = the tag without `v` (the workflow refuses a mismatch).
   One commit «Release X.Y.Z».
4. **The PR to main** (never a push to main): title «Release X.Y.Z», the body lists what changed and what was
   checked, and what needs a look on a PC (Windows-only parts tested with mocks). Watch it: CI runs twice
   (push and pull_request) on Ubuntu and Windows; wait for both, fix any red (a flaky test is a bug to fix,
   e.g. a fixed date that went stale, a background thread of another test). Merge with a merge commit when
   green, the merge state clean, and the user asked for the release.
5. **The Release workflow** on `main` with the tag: `actions_run_trigger`, `release.yml`, ref `main`,
   inputs `{"tag": "vX.Y.Z"}`. It builds the launcher and the installer, signs `SHA256SUMS.txt`, checks the
   signature with the app's key and publishes.
6. **Check what was published** (`get_release_by_tag`): not a draft; `prerelease` true for a beta only; the
   assets `Verbaliox-Installer-vX.Y.Z.exe`, `Verbaliox-vX.Y.Z.zip`, `Verbaliox.exe`, `SHA256SUMS.txt`,
   `SHA256SUMS.txt.minisig`; the body begins with the English section. Tell the user, with the link and
   what to look at on the PC.

## A build without a tag

`actions_run_trigger` `release.yml` on the working branch with `{"tag": ""}`: the launcher (`build_exe.py`) and
the Inno Setup installer compile; nothing is published. Use it after changes to `run.py`, `build_exe.py`,
`installer/`, `setup.bat`, `update.bat`.
