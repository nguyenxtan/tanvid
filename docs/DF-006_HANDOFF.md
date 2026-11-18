# DF-006 implementation handoff to Claude

PO approved DF-005. Base commit: `684821d538e51f246128dd5d560d5e8605692f75`.
At handoff the repository was clean; no DF-006 product code is implemented yet.
The user explicitly requested continuing through Claude when Codex hits limits.

## Authorized task

- Make medium FP16 the provisional default (currently defaults still say small).
- Add normalized segments with stable IDs, timestamps, unchanged original text,
  review status and reasons. Detect invalid timestamps, duplicates, suspected
  hallucinations and low confidence. Never silently invent/correct dialogue;
  heuristic flags are not proven hallucinations and must be labeled accordingly.
- Evaluate VAD/silence handling and decoding settings with measured comparisons.
- Benchmark an additional authorized drama-like Mandarin dialogue sample with
  a publisher/human reference independent of model output. Compare the existing
  AliMeeting baseline using the SAME DF-005 scoring as well.
- Preserve all DF-005 original records for traceability; keep raw inference
  results before any normalization/flags. Respect the existing 60 GB quota.
- Add tests, documentation, request independent Claude cross-review, resolve
  blocking findings and commit. Stop after DF-006 for PO approval.
- No translation, diarization, TTS, frontend or upstream integration.

## Existing implementation and evidence

Read parent `../AGENTS.md`, `../CLAUDE.md`, README, `backend/transcription.py`,
`backend/whisper_worker.py`, `backend/audio.py`, `backend/workspace.py`,
`models.lock.json`, tests and `docs/DF-005_BENCHMARK.md`.
DF-005: 64 tests pass, models already downloaded in `data/workspace/models`.
Host Apple M4 / macOS 15.6 / ARM64 / 16 GiB. MLX/Metal 0.32.4,
mlx-whisper 0.4.3. Both multilingual small and medium FP16 files verified.
Existing 156.54 s AliMeeting source and human reference under
`data/workspace/benchmarks/alimeeting`; recorded raw benchmark artifacts under
`benchmarks`. Medium baseline strict CER 269/828 = 32.4879%, median inference
13.249 s. Small 39.8551%, 6.221 s. See full documented limitations.

## Additional sample research, already done

Promising public, permissively licensed human role-play source:

- University of Texas at Austin / COERLL **Chinese Dialogues**, Wen-Hua Teng.
  Official page: https://coerll.utexas.edu/coerll/oer/chinese-dialogues-podcast/
- Publisher explicitly lists **CC-BY**, creative realistic social/family/school
  scenarios, and downloadable human-written full simplified/traditional transcripts.
- Official public folder linked by that page:
  https://drive.google.com/drive/folders/1NBFhcdv83ltni8fwhU7iLHpEmFzxCFbO
- Public folder HTML can be fetched with urllib without login; it lists 21 pairs
  of `chinese-dialogues-epNN.mp3` and `.pdf`. Targeted filename/ID extraction is
  enough; avoid printing the entire ~774 KB HTML.
- Example episode 1 audio ID: `1lkGoANYxi5vd5cWqk_Xm3GWxd7Odl2RY`;
  episode 1 PDF ID: `1D3qs_NTKLm4z4tgZKurhF4v_o3-B_-fr`.
- Example episode 4 audio ID: `13Lxp1j3a8kFIuCAlgAqljt6pBDboj50D`;
  episode 4 PDF ID: `17zxeWnzD0_hcGa-lhqoiFb4Y9Ht5tkc0`.
- Standard public Drive download URL is
  `https://drive.google.com/uc?export=download&id=FILE_ID` (verify actual response
  type and bounds). Read a few transcript PDFs to select a continuous scene
  BEFORE inspecting ASR hypotheses. Use actual publisher Chinese text, not a
  generated transcript. Verify audio/text alignment, record hashes/attribution
  and license version if stated in the PDF. Educational scripted role-play is
  a drama-like proxy, not actual scored TV drama; disclose lack of background
  music/acting intensity and any sample-length limitation. Do not concatenate
  unrelated clips and claim it was a continuous scene.

Rejected/limited candidates: BAAI EmotionTalk and EmoDialogCN are gated (401),
CC BY-NC-SA; do not bypass gates. EmoDialogCN public example scripts are ASR
outputs/English prompts, so cannot be trusted Chinese ground truth. TV-derived
datasets often lack audio redistribution rights. Synthesized DuplexDrama is not
real human dialogue. UT/COERLL is the best next lead.

## Execution

Continue autonomously within scope. Prefer a small understandable change;
thresholds and VAD/settings must be documented and benchmarked, not claimed as
automatic accuracy improvements. Compare baseline/settings on identical audio;
keep original results even if quality worsens. An energy gate is only silence
detection, not a trained speech VAD; label it accurately. If using a trained VAD,
pin its artifacts and include its cache in workspace quota. Store portable
benchmark records with no absolute private paths. Run the full suite, check
dependencies and upstream cleanliness, then independent Claude cross-review.
Report measured CER/time deltas, flag counts/examples, dataset limitations,
tests, commit SHA and blockers to the coordinator. Do not start DF-007.
