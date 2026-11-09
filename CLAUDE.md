## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues (`gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.

## Repo layout

The repo root is for developing this project. Everything users install lives in the self-contained `skill/` directory (`SKILL.md`, `AGENTS.md`, `PROTOCOL.md`, `scripts/`, `prompts/`). Files in `skill/` must not link to root-level files such as `GLOSSARY.md`, since those are not shipped.
