# `hooks/` — not wired into the plugin

`pre-bash.py` blocks destructive Bash commands. It is **deliberately not registered**
in `.claude-plugin/plugin.json`, and this directory deliberately has no `hooks.json`.

The reason is that a plugin's `hooks/hooks.json` is auto-discovered at the plugin
root **regardless of what `plugin.json` declares** — measured 2026-08-26 by installing
the plugin and reading `claude plugin details`, which reported 7 hooks when
`plugin.json` declared 5. Leaving a `hooks.json` here is therefore the same as
shipping its hooks. The two it used to carry both had to go:

- `UserPromptSubmit` → forbidden in this setup. `oh-my-heroacademia`'s `route_emit.py`
  occupies that event, and a second hook on it breaks routing.
- `PreToolUse` → ungated. It would fire in every project, not only inside a campaign,
  which is the false-positive class that gets a hook switched off.

`pre-bash.py` and its tests stay because they work and are cheap to keep. Wiring it
back means adding it to `plugin.json` **with an activation gate**, the way every
`skills/harness/hooks/*` entry is gated. Do not put a `hooks.json` back in this
directory to do it.

There are two gates in that directory, not one, and picking the wrong one ships a
hook that fires everywhere. Most entries gate on `board.json` `status: "active"` via
`_harness_common.is_harness_active()`. `self-reflect-stop.py` does not read
`board.json` at all -- it gates on `harness-tasks.json` existing *and*
`.harness-active` being gone, because it fires precisely when the task loop has
finished. A `PreToolUse` hook has no campaign of its own, so it wants the first
form.
