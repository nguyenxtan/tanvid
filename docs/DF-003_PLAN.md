# DF-003 media foundation

Scope: the approved DF-003 request. No transcription, translation, TTS,
frontend, model installation, paid APIs, or upstream integration.

Design decisions: standard-library Python service and a small JSON CLI; no
new Python dependencies or database migrations. FFprobe validates container
and stream metadata, not full frame decode. Allow local MOV/MP4, Matroska/WebM,
and AVI inputs only; disable network protocols and playlist demuxers.
Require finite positive duration, positive dimensions, known video/audio
codecs and valid channels/sample rates; silent video is valid. Check file size
against both stat and probe metadata. Ignore attached cover images as video.

Configuration: `DRAMAFLOW_WORKSPACE` defaults to `data/workspace` relative to
the repository root. Quota is 60 GB (60,000,000,000 bytes), counting all file
bytes including staging and manifests. Keep 1 GiB physical free headroom.
Reject symlinks within the managed workspace. A cooperating-process flock
serializes imports. Preflight reserves source bytes plus 64 KiB for metadata;
stage the bounded copy, revalidate, then atomically publish an import directory.
Preserve the source. Fail closed on storage/probe errors; clean failed staging.

Files: `backend/workspace.py` for config/usage/preflight/locking,
`backend/media.py` for metadata validation/import and CLI,
`scripts/media.sh` for cwd-independent invocation,
`scripts/create_sample.sh` for a reproducible synthetic authorized fixture,
and `tests/test_media.py` for service and storage contracts.

- [x] Install Homebrew FFmpeg/FFprobe; verify Mach-O ARM64 and runtime versions.
- [x] Write failing tests for real media validation/import, invalid inputs,
      quota and physical capacity, rollback and concurrent imports.
- [x] Implement services and CLI; pass the complete test suite (23/23 pass).
- [x] Run actual sample import and record metadata, quota and disk results.
- [x] Update docs; obtain Claude cross-review (no blocking findings).
- [x] Commit all changes as the final step; report evidence and stop for PO approval.

Review focus: source changes during import, failed copies/probes, workspace
symlinks, existing files counting toward quota, simultaneous imports,
invalid/unknown metadata, missing binaries and subprocess timeouts.
