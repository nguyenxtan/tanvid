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
| LIM-009 | SIGKILL of a CLI parent or default SIGTERM of a library caller can leave a live MLX worker until inference completes, consuming GPU memory; CLI graceful cancellation does reap it. | Add a parent-death watchdog or equivalent worker supervision. |
| LIM-010 | Model HTTP reads have a 60-second socket timeout and size bounds, but no overall download deadline. A slow connection can hold the workspace lock. | Add an overall bounded download deadline. |
| LIM-011 | Model files are revalidated before returning a cached transcript; missing models can be downloaded despite an already-valid result. | Allow result-only cache reuse before model preparation with the same pinned identity. |
| LIM-012 | The energy gate is loudness-based silence detection, not a trained VAD. Quiet far-field speech falls below it (all 4 AliMeeting `text_over_detected_silence` flags were real speech) and music/effects count as sound. | Evaluate a pinned trained VAD on drama audio with music, within quota. |
| LIM-013 | Review flags cannot detect plausible wrong words (e.g. homophones); several thresholds were adjusted after seeing DF-006 outputs, so flag precision/recall is unmeasured. | Measure flags against a separate human-reviewed set. |
| LIM-014 | Whisper can skip a whole 30 s window (observed after a spoken English title). It is only reported via `possible_missed_speech`, not prevented, and that check depends on the energy gate. | Evaluate prevention (e.g. targeted re-decoding of uncovered spans) in a later phase. |
| LIM-015 | Results now store raw segments (tokens) under the unchanged 4 MiB result limit; DF-005 (schema 2) cached transcripts are not reused and remain counted. | Size limits by duration; add safe cache pruning. |

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

DF-005: model and transcription staging shares LIM-001/LIM-002; graceful worker
interruption is handled, hard-kill leftovers are counted and require manual
recovery. Downloads restart rather than resume unpublished models. One public
156.54-second meeting excerpt is not a drama-wide accuracy benchmark; overlap,
disfluencies, number formatting and script variation affect strict CER. Peak
process RSS and MLX allocator peaks are separate, overlapping memory views.
See `DF-005_BENCHMARK.md` for full benchmark limitations and measured results.

DF-006: the energy gate, review flags and missed-speech check are heuristics
(LIM-012–LIM-014). Only two short public samples were benchmarked; COERLL is
clean scripted educational role-play, not real drama with music. See
`DF-006_REVIEW.md` for measured results and disclosed post-hoc adjustments.
