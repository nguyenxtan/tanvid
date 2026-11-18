# AliMeeting benchmark materials

Source: **AliMeeting**, supplied by Alibaba Group; Fan Yu, Shiliang Zhang,
Yihui Fu, Lei Xie, Siqi Zheng, Zhihao Du, Weilong Huang, Pengcheng Guo,
Zhijie Yan, Bin Ma, Xin Xu and Hui Bu, *M2MeT: The ICASSP 2022 Multi-Channel
Multi-Party Meeting Transcription Challenge*, ICASSP 2022.

- Official dataset and download links: <https://www.openslr.org/119/>
- Collection/annotation description: <https://arxiv.org/abs/2110.07393>
- License: **Creative Commons Attribution-ShareAlike 4.0 International**,
  <https://creativecommons.org/licenses/by-sa/4.0/>,
  legal code: <https://creativecommons.org/licenses/by-sa/4.0/legalcode>.

The official release explicitly licenses the dataset under CC BY-SA 4.0.
The license permits copying, adaptation and use including commercial use,
subject to attribution, indicating changes and ShareAlike for adapted material.
No paid access, personal account, scraping of proprietary dramas, or separate
private permission is being relied on for this benchmark.

The excerpt/reference and any benchmark transcripts derived from this audio
are distributed here under **CC BY-SA 4.0**, with this attribution and no
additional restrictions. This notice concerns these benchmark materials,
not an assertion that unrelated project code is dataset-licensed.

Changes: select a continuous excerpt from the first far-field session, end
at a complete annotation boundary within 120–180 seconds, retain microphone
channel zero, and add a black video wrapper solely to exercise the existing
video/audio pipeline. No speech synthesis, artificial music/noise, transcript
generation by ASR, or model-hypothesis edits are used to create the reference.
The exact source members, times, hashes and publisher text are in `reference.json`.

Reference verification: use the publisher's released TextGrid annotations and
check the source member, timeline and speaker tiers against the selected audio.
These annotations are independent of both benchmarked models. This work does
not claim a new independent human listening/transcription audit.

Limitations: meeting-room conversation differs from dramatic delivery; natural
room acoustics/overlap are retained, but there is no controlled background-music
condition. A single short excerpt cannot establish population-level Mandarin
accuracy, accented-speech accuracy, emotional dialogue performance or training
data exclusion. Simple start-time-ordered CER penalizes overlapping speakers
and is not AliMeeting's permutation-invariant multi-speaker challenge score.
