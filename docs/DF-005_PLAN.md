# DF-005 speech recognition and MLX benchmark

Approved scope: native Apple Silicon MLX Whisper transcription, two measured
multilingual configurations, licensed real Chinese dialogue with independent
reference, quota including models, reusable validated results and interruption
recovery. No translation, diarization, TTS or frontend.

Design: pin multilingual small/medium FP16 repositories to immutable revisions
and expected file sizes/hashes. Download regular files directly inside the
workspace under its existing lock; avoid symlinked/out-of-quota Hugging Face
caches. Incomplete downloads never become valid models. Extract speech audio
through DF-004, then run inference in an isolated process with offline model
loading, Metal GPU verification, timeout and process-group cleanup.

Cache keys include audio SHA, model revision/weights and decoding options.
Validate structured segment timestamps/text/confidence fields and a checksummed
result envelope before reuse. Publish JSON atomically. Failed inference leaves
no completed result. Runtime model caches and benchmark assets count toward the
same 60,000,000,000-byte workspace quota and 1 GiB free-disk headroom.

Benchmark: use the official AliMeeting CC BY-SA 4.0 conversational meeting
audio and publisher-provided reference annotations, not either model's output.
Select one fixed 2–3 minute excerpt before inspecting model hypotheses; retain
overlap and all speakers. Report normalized character error rate (CER) and its
limitations, fresh-process model load/inference/end-to-end time, real-time
factor, process high-water RSS, MLX allocator peak, on-disk bytes and hashes.
Do not sum overlapping unified-memory metrics or describe a tiny single-clip
test as general model accuracy.

- [x] Verify M4/16 GiB, Metal execution, package compatibility and pinned models.
- [x] Obtain/license/document sample and publisher-verified reference.
- [x] Add focused tests, reusable model/transcription service and CLI (64 tests pass).
- [x] Run both configurations twice on identical audio, compute reference-based CER.
- [x] Document measured recommendation, limitations, samples and storage usage.
- [x] Claude cross-review; resolve blocking segment/RTF findings, tail handling
      and two model-integrity findings with regression tests. Native fractional
      duration smoke passes. Commit as the final step, then stop for PO approval.
