# Conventions

- **Docstrings**: `ARCHITECTURE:` / `WHY:` / `TRADEOFF:` prefixed comment blocks on non-obvious decisions (see `trading/pyproject.toml`, `dialectic/llm/*.py` for the idiom). Write them when making a non-obvious choice; don't narrate obvious code.
- **Commit messages**: house style with `--` em-dash flourish, e.g. `fix(trading): move the five room tokens out of the books and into the environment -- same secrets, new home`. Check `git log --oneline` before committing. Commit directly to master (user-confirmed; no feature branches, no asking).
- **Minimal diffs**; match the surrounding file's idioms.
- **Docs are amended beside, never silently edited** — dated amendment stamps next to the original text (applies to design docs/specs in `docs/`).
- `trading/tools/` modules stay stdlib-only at runtime (deliberate; keeps CLI tools dependency-free for cron).
- Python: type hints per surrounding file; pydantic models for API schemas; migrations are numbered SQL files in `dialectic/migrations/` (`011` current), `dialectic/schema.sql` is the fresh-DB baseline and must be kept in sync.
- Never introduce Docker artifacts (see `mem:core`).
