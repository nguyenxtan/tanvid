# DramaFlow / tanvid project rules

## Collaboration

- Request Claude cross-review when needed. The user has authorized this within
  the project; routine review does not require repeated permission.
- If Codex reaches its quota, check Claude availability/quota using available
  tools and delegate the remaining implementation to Claude if possible.
  Pass the objective, current changes, tests and remaining work. Only claim
  successful quota checks or handoffs when confirmed by tools.

## GitHub workflow

- Public repository: `https://github.com/nguyenxtan/tanvid`.
- Commit and push coherent, verified work regularly. Use task branches and
  merge reviewed changes when appropriate; the user has authorized this
  ongoing workflow. Do not fabricate merges when there is nothing to merge.
- Run checks appropriate to each change and resolve blocking review findings
  before merging. Preserve task IDs and useful commit history.
- Keep `.env`, credentials, `.venv`, model weights and runtime `data/` out of Git.
  Retain benchmark source attribution and applicable data licenses.
- Respect each task's PO approval boundary. Publishing authorized completed
  work does not authorize starting the next phase.
