# Deferred limitations

DF-003 accepted non-blocking follow-ups, tracked for future PO-approved work:

| ID | Limitation | Future resolution |
| --- | --- | --- |
| LIM-001 | Atomic publication is not power-loss durable; imports do not fsync files/directories. | Add durable publication and recovery checks. |
| LIM-002 | SIGKILL/crash staging leftovers remain counted against quota. | Add safe recovery/sweep under the workspace lock; never remove active work. |
| LIM-003 | Workspace flock waits without a timeout. | Add a bounded wait and useful busy diagnostics. |
| LIM-004 | Relative CLI input paths resolve against repo root. | Consider caller-relative arguments with compatibility documentation. |
| LIM-005 | Manifests store absolute paths; tools are resolved through PATH. | Define workspace relocation/tool-version policy. |
| LIM-006 | Advisory locking does not control arbitrary external workspace writers; repository-root workspace encounters virtualenv symlinks. | Keep dedicated local workspace; consider stronger isolation if scope expands. |
| LIM-007 | DF-003 growth-during-copy, cross-process locks, CLI exit codes were manually reviewed, not all independently automated. | Expand focused regression coverage when touching these behaviors. |
| LIM-008 | A corrupt optional original audio cache remains on disk/in its manifest when preservation is not requested; valid speech is reused with `original: null`. It remains counted and is revalidated on subsequent calls. | Repair with `--preserve-original`; add explicit safe cache pruning/reconciliation later. |

Media metadata validation is not full video-frame decode validation. Only the
documented local container families are supported. No processing-codec
compatibility beyond successful probing is promised.

DF-004 status: cross-process audio cache locking and CLI success/SIGTERM exit
behavior now have automated coverage. The original video-import growth-during-copy
scenario remains manually reviewed. LIM-001 through LIM-006 remain open.
Audio extraction shares those constraints. SIGKILL can leave a size-bounded
FFmpeg child finishing unpublished staging; graceful cancellation and timeouts
are covered and kill/reap the child. If both publication and rollback fail,
`replaced-*` recovery backups remain counted toward quota.
Cleanup I/O failures emit a warning and retain affected files rather than masking
the extraction result. CLI cancellation uses exit 130 for both SIGINT and SIGTERM.
Reservations intentionally favor capacity safety over accepting every file that
might ultimately fit; the launcher inherits the trusted local Python environment.
