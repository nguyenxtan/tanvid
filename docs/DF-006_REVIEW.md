# DF-006: medium default, reviewable segments, silence/decoding comparison

Measured 2026-11-18 on the same Apple M4 / macOS 15.6 ARM64 / 16 GiB host as
DF-005, native MLX 0.32.4 / mlx-whisper 0.4.3 on `Device(gpu, 0)`, pinned
multilingual **medium FP16** (`models.lock.json`, unchanged). No remote inference.

## Decisions

- **Provisional default model: medium FP16** (`MediaService.transcribe`,
  `TranscriptionService.transcribe`, CLI `--model`). Evidence: DF-005 AliMeeting
  32.49% vs small 39.86%, and the new COERLL sample **0.59% vs small 10.88%**
  (2 vs 37 edits / 340 characters). Small remains available for speed (3.52 s vs
  9.63 s median inference on COERLL).
- **Provisional default decoding profile: `df005`** (unchanged DF-005 options).
  No tested alternative improved CER on either correctly-trimmed sample.
  The alternatives remain selectable with `--profile` for further evaluation.
- Every result now keeps the **raw model segments verbatim** and adds
  normalized segments with stable IDs, unchanged original text/timestamps,
  review status and evidence-carrying reasons. Nothing is corrected.

## Samples and references

| Sample | Audio | Reference | Scored characters |
| --- | --- | --- | ---: |
| AliMeeting R8001_M8004 (DF-005, unchanged) | 156.54 s far-field meeting, 4 speakers, 11.5% overlap | Publisher TextGrid | 828 |
| COERLL Chinese Dialogues ep. 20, Dialogue #70 | 124.61 s studio-recorded family scene, 3 speakers (mother, son, father) | Publisher transcript PDF | 340 |

**COERLL provenance.** UT Austin COERLL, *Chinese Dialogues* by Wen-Hua Teng
(<https://coerll.utexas.edu/coerll/oer/chinese-dialogues-podcast/>). Downloaded
by pinned Drive file ID from the publisher-linked public folder; no login,
gate or bypass. License: the resource page states **CC-BY**; it does not state
a version on the resource itself, and the site's CC badge links CC BY 4.0. The
PDF contains no license text. Full attribution:
[benchmarks/coerll/ATTRIBUTION.md](../benchmarks/coerll/ATTRIBUTION.md).

- `chinese-dialogues-ep20.mp3`: 1,307,804 B, SHA-256
  `6dd9918ade3f97d01e2eb7a98ef73396ff8c668b1c6612a2f280bcc0320d4ab0`
  (MP3 80 kbps mono 44.1 kHz, 130.56 s; ID3 date 2012).
- `chinese-dialogues-ep20.pdf`: 283,860 B, SHA-256
  `8911f208e4656f33cc72b94c2d19f46488c0c9c6e3aa551925647332959801e4`
  (retained in `benchmarks/coerll/`).
- Validated speech WAV for the scored excerpt: SHA-256
  `34cc06002b02dfd0fbafc646db98aa908872b08428ff3a23c05bbafbd77db40b`.

**Selection order.** Transcript PDFs for episodes 1–20 were read first;
Dialogue #70 was chosen because it is a single continuous, conversational
three-person family scene and, unlike most other episodes, its transcript has
no alternate wordings (`(or …)`) or optional parenthesized words that make a
single reference ambiguous. The reference is the publisher's Simplified
section, parsed deterministically (`parse_publisher_dialogue`): speaker labels
removed, wrapped lines joined, no characters added, corrected or converted.
Tests re-extract it from the committed PDF.

**Alignment correction (disclosed).** After selection, a small-model pass was
used only to check where the scene sits in the audio. It suggested the episode
contained only the scene, so the first DF-006 runs used the full episode. The
medium runs then showed the audio opens with a **spoken English title**
("Episode 20 … Dialogue 70", ~0.7–5.4 s) that is not in the dialogue text. The
excerpt now starts at a fixed cut at **5.95 s**, the quietest 10 ms frame (−71
dBFS) between the title and the first turn, found by energy analysis; the prep
script fails if the cut is not silent. The remainder of the episode is unedited
and ends at 130.56 s. The reference text did not change. The full-episode runs
are retained as a **diagnostic** record (`df006-coerll-full-episode.json`), not
as the primary score. ASR output was never used as reference text.

## Profiles compared (identical audio, model, scoring)

| Profile | Change from DF-005 |
| --- | --- |
| `df005` | None: temperature 0, no previous-text conditioning, generic Simplified prompt |
| `energy_gate` | Decode only energy-gate non-silent regions (`clip_timestamps`), 600 ms merge, 250 ms pad |
| `energy_gate_coarse` | Same gate, merging gaps < 3 s and 500 ms pad (skips only long silences) |
| `temperature_fallback` | Whisper fallback temperatures 0.0–1.0 on compression/log-prob failure; fixed seed 0 |
| `silence_skip` | Word timestamps + MLX Whisper `hallucination_silence_threshold=2.0` |

The **energy gate is silence detection, not a trained VAD**: frame RMS (30 ms)
above max(10th-percentile floor + 12 dB, −60 dBFS). Audio with < 12 dB contrast
between the 95th and 10th percentile (constant tone, wall-to-wall music), or
non-zero audio where no region survives (e.g. quiet speech entirely below the
−60 dBFS floor), is marked *inconclusive* and decoded in full. Only exact
digital silence yields no regions. A quiet speaker inside otherwise louder
audio can still fall below the threshold (LIM-012). No trained
VAD model or extra cache was added. `energy_gate_coarse` was added after the
first `energy_gate` result as a controlled test of the fragmentation hypothesis.

Two fresh worker processes per profile; order rotated between runs. Each
profile produced **identical text in both runs** on every sample.

### AliMeeting (156.54 s, 828 reference characters)

| Profile | CER | Edits | Δ edits vs DF-005 | Inference median (range) | Δ vs DF-005 13.249 s | Segments | Needs review |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `df005` | 32.49% | 269 | **0** | 14.143 s (13.035–15.251) | +0.894 s | 52 | 4 |
| `energy_gate` | 64.86% | 537 | +268 | 25.720 s (25.558–25.882) | +12.471 s | 53 | 21 |
| `energy_gate_coarse` | 33.33% | 276 | +7 | 13.104 s (13.101–13.106) | −0.145 s | 52 | 4 |
| `temperature_fallback` | 32.49% | 269 | 0 | 13.300 s (13.166–13.433) | +0.051 s | 52 | 4 |
| `silence_skip` | 35.87% | 297 | +28 | 21.106 s (19.631–22.582) | +7.857 s | 63 | 5 |

The `df005` profile reproduces the DF-005 medium transcript **character for
character** (test-verified). Its inference time differs from DF-005's median by
+0.894 s with the same model/options, which indicates the host run-to-run
variation; time differences of about a second are not meaningful here.

### COERLL Dialogue #70 (124.61 s, 340 reference characters)

| Profile | CER | Edits | Inference median (range) | Segments | Needs review |
| --- | ---: | ---: | --- | ---: | ---: |
| `df005` (medium) | **0.59%** | 2 | 9.631 s (9.438–9.824) | 24 | 0 |
| `df005` (small, model comparison) | 10.88% | 37 | 3.515 s (3.469–3.561) | 27 | 0 |
| `energy_gate` | 17.06% | 58 | 23.122 s (22.813–23.431) | 28 | 11 |
| `energy_gate_coarse` | 0.59% | 2 | 8.998 s (8.876–9.120) | 23 | 0 |
| `temperature_fallback` | 0.59% | 2 | 9.163 s (9.065–9.261) | 24 | 0 |
| `silence_skip` | 14.41% | 49 | 13.647 s (12.974–14.320) | 24 | 0 |

Medium's two remaining errors are homophones: `小钟` for the name `小中`, and
`帮他` for `帮她`. Most `silence_skip`/`energy_gate` loss is the model switching
to **Traditional characters** mid-transcript (e.g. `我們看了電腦以後`) plus
dropped short turns (`对`, `好啊`). The DF-005 scoring does not convert scripts,
so these count as errors; that is intended strict scoring, not a reference flaw.

### Full-episode diagnostic (title included, same 340-character reference)

| Profile | CER | Edits | Missed-speech spans |
| --- | ---: | ---: | --- |
| `df005` / `temperature_fallback` | 30.59% | 104 | 4 spans, 20.32 s |
| `energy_gate` | 19.41% | 66 | none |
| `energy_gate_coarse` | 20.00% | 68 | 4 spans, 20.78 s |
| `silence_skip` | 30.00% | 102 | 4 spans, 21.05 s |

With the English title in the first 30 s window, medium emitted `Episode 20` /
`Dialogue 70` and then **skipped to 30.0 s, silently dropping ~24 s of
dialogue** (the first seven turns). This is the most consequential failure
observed. The per-segment flags cannot see it (0 segments flagged), but the
new missed-speech check reports it (see below). The fine gate avoids this
failure by restarting decoding per region; that is why it helps only here.

### Interpretation

- **No setting is a general accuracy improvement.** Fine energy gating more
  than doubled AliMeeting errors and nearly doubled inference time: decoding
  36 short clips loses context, produced a looping hallucination (35–63 s), and
  dropped quiet far-field speech that measured below the gate. Coarse gating
  was neutral on COERLL and slightly worse (+7 edits) on AliMeeting.
- **Temperature fallback never triggered** on these samples (identical output
  to `df005`), so it has no measured benefit or cost yet.
- **`silence_skip` was worse on both samples** and ~50% slower.
- The fine gate is the only measured mitigation of the title-induced window
  skip, at a large cost elsewhere. Detecting the skip for review (below) was
  chosen over making a lossy setting the default.

## Review layer

Each published result contains, in order of derivation:

1. `raw_inference.segments`: the worker's model segments **verbatim** (tokens,
   seek, temperature, raw text) and the effective `decode_options`.
2. `silence`: deterministic energy-gate analysis of the exact audio.
3. `segments`: DF-005 normalized fields (`start_ms`, `end_ms`,
   `original_text`, `confidence`) plus `id`, `raw_index` and
   `review: {status, reasons[]}`. Status is `needs_review` or `unflagged`
   — never "correct" or "verified".
4. `excluded_raw_segments`: raw entries not published, with a reason
   (`empty_text`, `zero_length_timestamp`, `starts_after_audio_end`).
5. `review`: counts by reason/category, thresholds, the disclaimer, and
   `possible_missed_speech` spans.

IDs are `seg-<raw index>-<sha256(audio, index, start, end, text)[:10]>`:
identical for identical raw output, unique within a result, traceable to the
raw entry. Reuse validation re-derives segments, flags and summary from the
stored raw output and rejects tampering (test-covered).

Reasons carry `heuristic: true`, a category and the measured evidence.
Thresholds (also stored in every result):

| Code | Category | Rule |
| --- | --- | --- |
| `timestamp_clipped_to_audio_end` | timestamp | raw end > audio duration (clipped) |
| `overlaps_previous_segment` | timestamp | start < previous end |
| `implausibly_fast_speech_rate` | timestamp | > 12 scored characters/s |
| `long_span_little_text` | timestamp | ≥ 4 s and < 1 character/s |
| `duplicate_of_previous_segment` | duplicate | same comparable text as previous segment |
| `repeated_text_pattern` | suspected_hallucination | 1–8 character unit repeated ≥ 4 times (short single-character runs such as `对对对对` allowed) |
| `high_compression_ratio` | suspected_hallucination | > 2.4 (Whisper's threshold) |
| `likely_non_speech` | suspected_hallucination | window no-speech prob > 0.6 **and** (avg log-prob < −1.0 or text over measured silence) |
| `text_over_detected_silence` | suspected_hallucination | < 10% of the span is gate non-silent (skipped when inconclusive) |
| `known_artefact_phrase` | suspected_hallucination | contains a known Whisper artefact phrase |
| `prompt_echo` | suspected_hallucination | ≥ 4 characters and text is inside, or contains, the decoding prompt |
| `low_average_logprob` | low_confidence | avg log-prob < −1.0 |

`possible_missed_speech` lists gate non-silent spans ≥ 2 s covered by no
segment. Malformed raw timestamps (non-finite, negative, backward, unordered
starts) still fail the transcription, as in DF-005.

**Threshold changes made after seeing outputs (disclosed):** window-level
`no_speech_prob > 0.6` alone flagged 18 of 23 clean COERLL studio segments,
so it is now combined as Whisper's own skip rule does; `字幕提供` and
`网易云音乐` were added to the artefact list after the AliMeeting gate output
`字幕提供 网易云音乐队`; the missed-speech check was added after the
full-episode window skip. Flag precision/recall is therefore not an
independent estimate.

### Flag results

| Sample / profile | Segments | Needs review | Reasons | Missed speech |
| --- | ---: | ---: | --- | --- |
| AliMeeting `df005` | 52 | 4 | text_over_detected_silence 4, likely_non_speech 1 | none |
| AliMeeting `energy_gate` | 53 | 21 | high_compression_ratio 14, overlaps_previous 5, likely_non_speech 4, text_over_silence 4, artefact phrase 1, low logprob 1 | 3 spans, 15.29 s |
| AliMeeting `silence_skip` | 63 | 5 | likely_non_speech 3, text_over_silence 3, fast rate 1, duplicate 1 | 2 spans, 7.61 s |
| COERLL `df005` | 24 | 0 | — | none |
| COERLL `energy_gate` | 28 | 11 | overlaps_previous_segment 11 | none |
| Full episode `df005` | 23 | 0 | — | **4 spans, 20.32 s** (6.29–30.00 s) |

Examples (verbatim from the records):

- True positive, looping hallucination — AliMeeting `energy_gate`
  `seg-0019-1229eda2f5` 51,260–53,260 ms `現在手機基本上沒有任何效果`:
  `high_compression_ratio` 4.21; the same two sentences repeat every 2 s from
  37 s to 63 s.
- True positive, artefact — AliMeeting `energy_gate` `seg-0000-d49589b5be`
  0–2,000 ms `字幕提供 网易云音乐队`: `known_artefact_phrase`, avg log-prob −1.12.
- True positive, dropped dialogue — full episode `df005`: missed speech
  6,290–9,250, 9,530–11,530, 14,000–24,370 and 25,010–30,000 ms.
- **False positives** — all 4 AliMeeting `df005` flags (e.g.
  `seg-0009-2ad4db57c6` 46,280–48,920 ms `嗯对这样我觉得范围更广一些`,
  `text_over_detected_silence`, non-silent fraction 0.0) overlap
  publisher-annotated speech. Quiet far-field speakers fall below the energy
  threshold. On far-field audio this flag is noisy.
- **Missed errors** — COERLL `df005`'s two homophone errors are unflagged;
  no heuristic here detects plausible wrong words. `unflagged` ≠ correct.

## Limitations

- Two short samples (≈4.7 minutes total). COERLL is **educational scripted
  role-play**: clean studio recording by speakers enunciating for learners, no
  background music, effects or acted emotional intensity, standard Mandarin
  only. It is a drama-like proxy, not a scored TV/short drama. Its near-zero
  CER must not be read as expected drama accuracy. Training-data contamination
  cannot be excluded for either public sample.
- Two runs per profile cannot provide confidence intervals; host load,
  power mode and thermals were not controlled. Times are MLX inference only;
  service end-to-end medians are in the records.
- Energy gating cannot separate speech from music/effects; drama soundtracks
  will make regions and the missed-speech/over-silence checks unreliable.
  Inconclusive audio disables silence-based flags rather than guessing.
- `no_speech_prob` is per 30 s window in MLX Whisper; `avg_logprob` and
  compression ratio are model diagnostics, not calibrated probabilities.
- CER is the strict DF-005 metric (no script conversion, no number
  normalization, start-time ordered multi-speaker reference).
- Results now store raw segments (tokens included). The 4 MiB result limit
  is unchanged; very long media may need it raised in a later phase.
- DF-005 cached results are not reused (schema 3 identity); they remain on
  disk and count toward quota until removed.

## Storage

Workspace after DF-006: **5,795,257,562 B used, 54,204,742,438 B remaining** (final, after review fixes)
of the 60,000,000,000 B quota (models 2.01 GB, benchmark assets 3.75 GB,
audio 25.4 MB, transcripts 0.78 MB). COERLL assets (MP3, PDF, two wrapper videos) add ≈ 24.3 MB. No new
models or VAD caches. New package: `pypdf==7.1.0` (BSD-3-Clause, pure Python)
for reproducible reference extraction; `pip check` clean.

## Reproduce

```sh
.venv/bin/python scripts/prepare_coerll.py
.venv/bin/python scripts/benchmark_settings.py \
  data/workspace/benchmarks/coerll/coerll-ep20-dialogue70.mkv \
  data/workspace/benchmarks/coerll/reference.json --name coerll --runs 2
.venv/bin/python scripts/benchmark_settings.py \
  data/workspace/benchmarks/alimeeting/mandarin-dialogue.mkv \
  data/workspace/benchmarks/alimeeting/reference.json --name alimeeting --runs 2
```

Full-episode diagnostic (title included):

```sh
.venv/bin/python scripts/prepare_coerll.py --full-episode-diagnostic
.venv/bin/python scripts/benchmark_settings.py \
  data/workspace/benchmarks/coerll/coerll-ep20-full-episode.mkv \
  benchmarks/coerll/reference-full-episode.json --name coerll-full-episode --runs 2
```

Records: `benchmarks/df006/` (full payloads, raw segments, reviews, metrics;
no absolute paths). DF-005 records `benchmarks/mlx-results.json` and
`benchmarks/reference.json` are byte-identical to DF-005 (test-pinned SHA-256).
No translation, diarization, TTS, frontend or upstream integration.

## Independent review and fixes

A separate read-only Claude reviewer recomputed every table row from
`benchmarks/df006/*.json` (all matched). It also confirmed that the DF-005
records are byte-identical, that no text or timestamp is corrected, that the
5.95 s cut lies in silence, that the full-episode window skip happens as
described, and that 91/91 tests pass with `pip check` clean.

- **Blocker B1 (fixed):** quiet but contrasty audio, for example −63 dBFS bursts
  over a −90 dB floor, produced zero gate regions with `inconclusive=false`.
  `energy_gate` and `energy_gate_coarse` then decoded nothing and published an
  empty transcript with no review signal. Now any non-zero audio without
  regions is inconclusive and decoded in full. Failing tests reproduced it
  first: one for the detector and one end to end for both gated profiles.
- **Non-blocking, fixed:** single-character `prompt_echo` false positives
  (`是`, `中文`), now requiring ≥ 4 characters; partial `.part` downloads are
  removed on any failure; `--full-episode-diagnostic` makes that record
  reproducible (audio SHA-256 `9e7f522f…` re-verified); `requirements.txt`
  keeps its original order with `pypdf` inserted.
- **Non-blocking, accepted and documented:** post-hoc thresholds (LIM-013),
  duplicate detection only against the adjacent segment (non-adjacent loops
  rely on compression/repetition flags), and thin default evidence.

Neither fix changes any recorded flag. Tests re-derive every recorded segment,
flag and summary from the stored raw output. The only difference is the
newly added `prompt_echo_min_chars` threshold, and every original threshold is
unchanged. Cached results created before the fix are re-validated, rejected
on that summary difference, and rerun (verified natively: the COERLL `df005`
and `energy_gate` reruns gave the same 24/0 and 28/11 segments/flags).
Final suite: **93/93 tests pass**; `pip check` clean.
