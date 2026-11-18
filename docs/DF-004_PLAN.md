# DF-004 audio extraction plan

Implement the approved DF-004 request only; no transcription, translation,
TTS, frontend, models, or upstream integration. No new Python dependencies.

Design: `AudioService(MediaService)` with `extract(source, audio_track=0,
preserve_original=False)`, exposed as `MediaService.extract_audio` and CLI
`extract-audio SOURCE [--audio-track N] [--preserve-original]`.
The selected audio ordinal defaults to zero. FFmpeg produces speech WAV
PCM signed 16-bit little-endian, mono, 16000 Hz. Optional `original.mka`
stream-copies all audio tracks, retaining original codec/rate/channels.
Inspect source through existing MediaService; use stream duration where
available, otherwise container duration; require output duration within
max(0.25 seconds, 0.1% of expected duration).

Store results in `workspace/audio/<source-sha256-and-profile-key>/`, with
checksummed manifests. Revalidate PCM frame integrity and FFprobe metadata;
fully decode original audio for integrity. Reuse valid outputs without
re-extracting; if preservation is newly requested, retain valid speech WAV.

Storage: same 60 GB quota and 1 GiB headroom under the workspace flock.
Reserve bounded WAV bytes + original remux bound (source size + 1 MiB when
needed) + 64 KiB manifest. Apply per-child file-size limits so bad duration
metadata cannot grow an output beyond reservation. Reject classic WAV bounds
over 4 GiB. Recheck final storage before publishing. Invalid existing results
are replaced only after new results validate, with rollback on publish failure.

Subprocesses run with timeouts; on cancellation/exception kill and reap their
process group before staging cleanup. CLI SIGTERM/Ctrl-C exits safely.
SIGKILL/power-loss limitations remain tracked in `docs/LIMITATIONS.md`.

- [x] Add tests first: real speech WAV, preservation, duration/format/integrity,
      cache reuse/repair, absent audio, corrupt inputs, quota denial, child output
      bounds, timeout and signal interruption, CLI integration, 180-second sample.
- [x] Implement extraction, media integration and CLI; full suite 43/43 passes.
- [x] Generate/import/extract a 180-second original synthetic MP4; record timing,
      metadata and storage. No downloaded footage or third-party assets.
- [x] Update documentation and limitation backlog; Claude found no blocking findings.
- [x] Resolve review follow-ups with regression tests; commit all changes as the
      final step and stop for PO approval.
