# DF-005: native MLX Whisper benchmark and transcription

Verified 2026-11-18 on the actual **Apple M4**, macOS 15.6 ARM64, **16 GiB RAM**.
Native MLX reports `Device(gpu, 0)` and Metal available; every recorded inference
worker confirms `arm64` and the GPU device. No remote inference was used.

## Measured recommendation

**Recommend multilingual Whisper medium FP16 for quality on this target.**
It made 61 fewer reference-character edits than small (7.37 percentage points
lower CER, 18.5% relative error reduction), while transcribing the 156.54-second
excerpt in approximately 13.25 seconds. Small is the measured speed/storage
fallback. This recommendation is limited to the two tested configurations and
one meeting excerpt; neither result is accurate enough to claim unattended
subtitle quality without review.

| Metric | Small FP16 | Medium FP16 |
| --- | ---: | ---: |
| CER, lower is better | **39.86%** | **32.49%** |
| Character edits / reference characters | 330 / 828 | 269 / 828 |
| Model weights + config | 481,307,858 B | 1,524,925,180 B |
| Model size, decimal MB | 481.31 | 1,524.93 |
| Inference median, 2 fresh workers | 6.221 s | 13.249 s |
| Inference range | 5.043–7.399 s | 13.176–13.323 s |
| Inference real-time factor, median | 0.03974 | 0.08464 |
| Model load median | 0.127 s | 0.444 s |
| End-to-end service median | 7.853 s | 15.591 s |
| Peak process RSS, maximum across runs | 946,864,128 B (0.882 GiB) | 2,050,408,448 B (1.910 GiB) |
| Peak MLX allocator, maximum across runs | 1,277,588,358 B (1.190 GiB) | 2,215,927,254 B (2.064 GiB) |

Peak RSS uses macOS `getrusage(RUSAGE_SELF).ru_maxrss` bytes; MLX allocator peak
uses `mx.get_peak_memory()`, reset before model loading. They describe different,
potentially overlapping unified-memory views and **must not be added together**.
They are not a measured peak of whole-system physical memory. Medium RSS varied
from 943,620,096 to 2,050,408,448 bytes; raw per-run measurements are retained.
The MLX allocator is limited to 8 GiB, not the entire process to 8 GiB.

## Dataset authorization and reference verification

- **AliMeeting**, official Alibaba Group release, OpenSLR SLR119:
  <https://www.openslr.org/119/>.
- License: **CC BY-SA 4.0**. Benchmark audio/reference adaptations and derived
  transcript artifacts retain attribution and ShareAlike; see
  [benchmark attribution](../benchmarks/ATTRIBUTION.md).
- Downloaded the official `Eval_Ali.tar.gz`, 3,673,718,355 bytes, with bounded
  reads and workspace capacity checks. Gzip integrity check passes. SHA-256:
  `dc47343b2474b5ebcf458927e878155f6ddeb59c85e685b3645c32a1f9578d92`.
- Source audio: `Eval_Ali/Eval_Ali_far/audio_dir/R8001_M8004_MS801.wav`, first
  far-field microphone channel. Reference:
  `Eval_Ali/Eval_Ali_far/textgrid_dir/R8001_M8004.TextGrid`.
- Annotation SHA-256:
  `e5fe941174fe4140bb5923b7caf2cbdd68d8d2a86086e4f00c68afc90d09dbad`.
- Fixed excerpt: **0.00–156.54 s**, chosen as the latest complete utterance
  boundary within 120–180 seconds, before inspecting any model hypotheses.
  Four publisher-labeled speakers; **18.01 s** of annotated overlap (11.50%
  of excerpt duration). Their conversation concerns a mobile-phone product.
- Source PCM was selected from real human audio; black video was added only
  to exercise the existing media/audio pipeline. A 100 fps wrapper preserves
  the reference's 10 ms boundary precision. No synthesized dialogue or added
  music/noise, source enhancement, separation, or production diarization.
- Validated speech WAV SHA-256, identical for all trials:
  `e48b7dd16cd21f9823977a7ee17ecca895c6718aa7dc47887b815de5d68bf796`.

Ground truth is the **publisher's reference**, not AI-generated transcription.
Its original TextGrid is retained in `benchmarks/R8001_M8004.TextGrid`; tests
verify its SHA and reproduce the exact selected reference text/times/speakers.
The corpus paper describes human transcription and annotation of real meetings:
<https://arxiv.org/abs/2110.07393>. This is provenance/reference verification,
not a claim that a new independent human listening audit was performed here.

The official corpus describes naturally occurring room noise and reverberation.
No particular noise type or background music was independently labeled for this
excerpt. It is conversational meeting speech, not an acted short drama, and
does not establish performance with drama music, emotional speech or dialects.

## Method and limitations

Two fresh processes per model, alternating small/medium then medium/small.
Pinned repo revisions and weight/config SHA-256 are in `models.lock.json`.
Both use FP16, Chinese `language=zh`, `task=transcribe`, temperature 0,
no previous-text conditioning, no word timestamps, and the same generic
Simplified Chinese prompt: `以下是普通话简体中文转写。`. The prompt contains no
reference content. The service never translates or post-corrects the hypotheses.

Models were already downloaded and the filesystem cache was warm. Model loading
and inference are measured separately with Metal synchronization. Service time
also includes audio validation, model checksum verification and publication;
downloads are excluded. The first small trial was slower, consistent with warmup
effects; both raw trials are reported. Power mode, host load, temperature and
long-duration thermal throttling were not controlled. Two trials cannot provide
stable confidence intervals.

CER uses Levenshtein edits divided by 828 reference characters, after NFKC,
lowercasing and removing punctuation/symbols/whitespace. It does **not** convert
traditional/simplified characters, normalize spoken numbers to digits, or remove
human disfluencies/repetitions. All speakers' reference utterances are ordered
by start time; overlap and omitted fillers increase this strict score. This is
not AliMeeting's permutation-invariant challenge scoring and not diarization
accuracy. CER can exceed 100%; `1-CER` is not a calibrated accuracy probability.
Both repetitions produced identical text/CER for each model. Training-set
contamination cannot be excluded for a public corpus. More drama-like licensed
samples and human listening evaluation remain necessary before deployment.

## Actual transcription examples

Medium output, 13,000–19,000 ms:

```json
{"start_ms":13000,"end_ms":19000,"original_text":"首先,让我们确认一下产品的目标,人群,客户群这一块。","confidence":{"avg_logprob":-0.4353626361791638,"no_speech_prob":0.4660603404045105,"compression_ratio":1.1006711409395973}}
```

Errors are retained rather than silently corrected: the opening medium output
contains `进行编考会`, while the human reference says `进行一下这个研讨会`.
The full original Chinese outputs, segments, diagnostics and measurements are
in [the recorded results](../benchmarks/mlx-results.json). Confidence fields
are model diagnostics, not probabilities of correctness or reference accuracy.

## Implementation, storage and recovery

- `ModelStore` downloads only pinned files, validates byte counts/SHA-256,
  publishes atomically, and revalidates existing local weights. No Hub snapshot
  symlinks or unmanaged weights cache. Weights, partial files and source assets
  live inside the same quota-managed workspace. Network failures/interruption
  cannot turn incomplete files into a valid published model; reruns restart
  interrupted downloads. Hard-kill staging remains counted for manual recovery.
- `TranscriptionService` reuses DF-004 PCM extraction and executes local-only
  `mlx_whisper` in a fresh process with timeout/process-group kill and reaping.
  Native Metal is mandatory. Segment timestamps/text/diagnostics and measured
  metrics are validated before publishing a checksummed JSON envelope.
- Result identity includes audio hash, model revision/file hashes, package
  versions and all decoding options. A corrupt or inconsistent result is rerun.
  Native medium SIGTERM was exercised: exit 130, worker reaped, staging removed,
  and the previously completed result remained byte-identical.
- The same **60,000,000,000-byte** quota and **1,073,741,824-byte** disk reserve
  apply. Model downloads reserve expected files + 64 KiB; inference reserves
  16 MiB and limits each worker result/log file to 4 MiB.
- Measured workspace usage: **5,746,887,781 bytes**; quota remaining
  **54,253,112,219 bytes**. This includes models **2,006,233,938 bytes**,
  benchmark assets/archive **3,725,323,709 bytes**, audio **12,998,718 bytes**,
  transcripts **28,469 bytes** and prior imports. Free disk: approximately
  **114,452,955,136 bytes**. These are a snapshot and change with results/logs.
- `du`: project **6.6 GiB**, `.venv` **1.2 GiB**, workspace **5.4 GiB**, models
  **1.9 GiB**, benchmark assets **3.5 GiB**. Packages are outside workspace quota
  as before; they are pinned in `requirements.txt`. `mlx-whisper==0.4.3`,
  `mlx==0.32.4`, `mlx-metal==0.32.4`. Torch is a transitive package dependency;
  the measured inference engine is MLX, not Torch.

## Verification and approval gate

Automated tests cover normalization/CER, malformed segments/confidence,
checksummed result reuse/repair, interrupted inference, real-child timeout,
quota denial, bounded model download/hash validation, original TextGrid parsing
and source-reference/result-score reproducibility. Model inference is exercised
by the four real benchmark runs; lightweight cache tests isolate that boundary
and do not claim mocked measurements as performance results.

Full automated suite: **64/64 tests pass**. `pip check` reports no broken
requirements. Gzip archive verification passes, and native worker cancellation
preserves a completed result. Claude independently verified the original 59-test
suite, reference/scoring, all reported medians and memory/model-size claims.

Post-review fixes, each reproduced with a failing regression test then verified:

- Ignore MLX Whisper's empty instantaneous segments instead of failing the run.
- Preserve exact frame-derived `duration_seconds` for RTF computation/validation,
  independently of rounded `duration_ms`; cache schema bumped to 2.
- Clip final-window segment ends, drop wholly outside/zero-length segments and
  record `segment_adjustments`; malformed/backward/non-finite timing still fails.
- Reject unexpected model-directory files (including unpinned
  `weights.safetensors`, which the MLX loader otherwise prefers).
- Handle truncated HTTP bodies as model download errors with staging cleanup.

The final native MLX short-clip smoke test used **32,005 frames / 16,000 Hz =
2.0003125 seconds**, confirmed correct RTF and validated reuse. The four main
benchmark measurements predate these edge-case fixes; their model/options are
unchanged, and regression tests confirm the final normalizer preserves all
recorded segments and CER. Raw timings have not been relabeled as reruns.
Published benchmark artifacts omit absolute local result paths for portability.

Remaining low-priority review notes are tracked as LIM-009–LIM-011: hard-killed
parents can leave a live inference worker, model downloads have socket but no
overall deadline, and result reuse still prepares/revalidates models first.
These are deferred, not claimed fixed.

Upstream remains unchanged. No translation, speaker diarization, TTS, frontend
or paid APIs were implemented. Stop after DF-005 and wait for PO approval.
