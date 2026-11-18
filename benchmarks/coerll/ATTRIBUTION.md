# COERLL Chinese Dialogues benchmark materials

Source: **Chinese Dialogues**, by **Wen-Hua Teng**, published by the Center for
Open Educational Resources and Language Learning (**COERLL**), The University
of Texas at Austin. Episode #20, Dialogue #70 (audio recorded 2012; transcript
PDF created 2013-01-07).

- Resource page: <https://coerll.utexas.edu/coerll/oer/chinese-dialogues-podcast/>
- Publisher-linked public folder:
  <https://drive.google.com/drive/folders/1NBFhcdv83ltni8fwhU7iLHpEmFzxCFbO>
- License as stated by the publisher on the resource page: **CC-BY**
  (Creative Commons Attribution). The resource page does not state a version;
  the site's Creative Commons badge links
  <https://creativecommons.org/licenses/by/4.0/>. The PDF itself contains no
  license text. Metadata inconsistencies retained as found: PDF author "Wen Hua";
  MP3 ID3 artist "Wen-Hua Ting", album "Grammar Dialogues Podcast".

`chinese-dialogues-ep20.pdf` here is the unmodified publisher file
(SHA-256 `8911f208e4656f33cc72b94c2d19f46488c0c9c6e3aa551925647332959801e4`).
The audio is not redistributed here; `scripts/prepare_coerll.py` downloads it by
pinned file ID and verifies SHA-256
`6dd9918ade3f97d01e2eb7a98ef73396ff8c668b1c6612a2f280bcc0320d4ab0`.

Changes for benchmarking: the scored reference is the publisher's Simplified
Chinese text of Dialogue #70 with speaker labels removed and wrapped lines
joined (`reference.json`). The scored audio excerpt removes the spoken English
episode/dialogue title (0–5.95 s, cut in measured silence), keeps the rest of
the episode unedited, and adds a black video wrapper only to exercise the
existing pipeline. No speech synthesis, added noise/music, enhancement, or
ASR-generated or ASR-corrected reference text. Benchmark transcripts derived
from this audio are provided under the same CC BY attribution. This notice
concerns these benchmark materials only, not unrelated project code.

Limitations: educational scripted role-play recorded for learners — clear,
standard Mandarin without music, effects or acted emotional intensity. It is a
drama-like proxy, not a scored TV or short-drama sample.
