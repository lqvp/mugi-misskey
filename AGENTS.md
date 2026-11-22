# AGENTS.md

This repo documents how a Devin Bot runs its own Misskey account. When asked to reproduce it, follow docs/setup-with-devin.md step by step.

- Never write the Misskey token or the webhook secret to a file, commit, log or chat. Pass them through exec `env` secret bindings.
- Live state (affinity.json, state.json, wander.json) belongs in the Bot's memory folder, not in this repo; only the `*.example.json` templates are committed.
- Config values in this repo are dummies (misskey.example.com, examplebot). Keep it that way.
- Bump `CODE_VERSION` in relay/worker.js whenever you change it.
- Tests: `python3 -m unittest discover -s tests` and `cd relay && node --test test/`.
- Commits: English Conventional Commits.
