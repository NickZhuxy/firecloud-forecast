# Agent coordination

Before changing code, read `.agent-progress.md` in the repository root. It is the live coordination ledger for agents sharing this workspace and is intentionally ignored by Git.

## Working protocol

1. Claim the GitHub issue or bounded subtask in `.agent-progress.md` before editing.
2. Record the agent name, branch, intended files, dependencies, and current status.
3. Do not edit a file claimed by another active agent without coordinating first.
4. After each meaningful checkpoint, update the status, tests run, blockers, and handoff notes.
5. Keep durable requirements and acceptance criteria in GitHub Issues/Projects; keep only live execution state in `.agent-progress.md`.
6. Never write tokens, credentials, private URLs, or other secrets into the coordination file.

Agents in separate Git worktrees do not share ignored files. For cross-worktree coordination, use the linked GitHub Project and Issue comments as the source of truth.

## Shared planning links

- Project: <https://github.com/users/NickZhuxy/projects/2>
- Repository: <https://github.com/NickZhuxy/firecloud-forecast>
