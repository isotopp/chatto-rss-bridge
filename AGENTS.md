# Development guide

The instructions before the agent guardrails are shared by human developers and coding agents.

The project language is English. Keep code, tests, documentation, and commit messages in English.

## For developers

- Install dependencies with `uv sync`. Commit `uv.lock` when dependency resolution creates or changes it.
- Put package code in `src/chatto_rss_bridge/` and tests in `tests/`.
- Before sharing a change, run `uv run ruff check --fix`, `uv run ruff format`, `uv run ty check`, and `uv run pytest`.
- Keep user installation, configuration, and operation instructions in `README.md`.
- The repository copies of the `git-commit`, `tdd`, and `specialization-workflow` skills are in `.agents/skills/`; each `UPSTREAM.md` records its source.

## For agents

- Follow the applicable repo-local skill when the task calls for it. Use `specialization-workflow` for a requested epic, `tdd` for requested test-first work, and `git-commit` when asked to commit.
- Read the current code and documentation before changing behavior. Keep changes within the requested scope.
- Update `README.md` when installation, configuration, or operation changes.

## Agent-only guardrails

- Treat the Chatto API and RSS feed as external interfaces. Verify their current behavior before implementing against them; do not invent endpoints or payloads.
- Never commit bot credentials, tokens, or local `.env` files. Use a safe example file when configuration is introduced.
- Do not post to a live Chatto channel or set up a live cron job as part of tests.
- Keep feed parsing and message generation testable without network access, and use controlled fixtures for automated tests.
