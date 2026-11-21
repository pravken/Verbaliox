---
name: verbaliox-ui-check
description: Check Verbaliox's page in a real browser — run the CI browser checks (smoke and scenarios), take screenshots of a view or state to look at a design, or reproduce a UI bug with a Playwright script — against a server started the way CI starts it, on temporary data. Use after any change to static/ (CLAUDE.md asks for a browser check), when a scenario fails, and before showing the user a UI change.
---

# Verbaliox: the page in a browser

The approach follows Anthropic's webapp-testing skill (github.com/anthropics/skills, Apache 2.0): start the
server with a helper, wait for the page, look first, then act. The helpers here are written for this project.

## The server, as CI starts it

Never start uvicorn by hand for a check: three things were forgotten that way and cost a run each — the
token (the page stays locked), `PYTHONPATH=tests/stubs` (500s from `/api/vram`, no torch) and the demo data.

```bash
.claude/skills/verbaliox-ui-check/scripts/serve.sh [--port N] [--keep-data] -- <command>
```

It sets `VERBALIOX_TOKEN=smoke`, `VERBALIOX_SKIP_MIGRATION=1`, `PYTHONPATH=tests/stubs`, temporary
`VERBALIOX_DATA_DIR` / `VERBALIOX_MODELS_DIR` seeded by `tests/ui/seed.py`, waits for the server, runs the
command with `BASE` and `TOKEN` set, prints the server log when the command fails, and stops the server.
Port 8797 by default; give each parallel agent its own port (8799 is CI's).

## The checks of CI

```bash
.claude/skills/verbaliox-ui-check/scripts/check.sh            # smoke.mjs, then scenarios.mjs
SHOTS=/tmp/shots .claude/skills/verbaliox-ui-check/scripts/check.sh   # with screenshots of the steps
```

Judge by the exit code. A failing step prints its name and message; the scenario is in
`tests/ui/scenarios.mjs` (search the step name).

## Looking at a design

```bash
.claude/skills/verbaliox-ui-check/scripts/serve.sh -- \
  node .claude/skills/verbaliox-ui-check/scripts/shot.mjs /tmp/home.png --view dashboard --clip 0,0,900,420
```

Options: `--view dashboard|home|assistant`, `--js "<code run in the page>"` (open a dialog, enter
«Настроить», select a recording), `--width`/`--height` (the window's minimum is 1100×700), `--clip x,y,w,h`,
`--wait ms`, `--scale` (2 for what the user sees, 1 for a quick look). Read the PNG to see it. Take the shot
after the data has loaded (the hardware block and the widgets fill in after a moment).

## Writing a scenario or a one-off probe

- Put a new check into `tests/ui/scenarios.mjs` as a `step(...)`; prove it fails without the fix, then passes.
- The page's CSP refuses `page.waitForFunction` in CI's Playwright: poll with `page.evaluate` instead.
- CI on Ubuntu is slow: wait for a state (poll), never a fixed sleep that only works here.
- Smooth scrolls run on after `scrollTop = 0`: wait until the position holds before measuring boxes.
- A probe script that imports `playwright` runs from the repository (e.g. a temporary `tests/ui/_probe.mjs`,
  deleted afterwards), so the module is found.
- Page functions are globals (`switchAppView`, `renderDashboard`, `openModal`, `dbPrefs`…): call them through
  `page.evaluate`. The first-run wizard covers the page in a fresh data folder: remove `#first-run-wizard`.
