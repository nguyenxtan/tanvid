# DF-007 opening dialogue recovery

Use `--profile bounded_opening` to retry a clip with suspected missing opening
dialogue. It requests MLX Whisper windows capped at 10, 20 and 30 seconds,
then continues with normal decoding for the rest of the audio. Boundaries
within 10 ms of the audio end are omitted. The profile uses the same medium
FP16 model and retains the worker output, including the spoken title. The
default remains `df005`.

On the full COERLL episode, `df005` recognizes the English title and then resumes
at 30 seconds. `bounded_opening` emits Mandarin dialogue at 6–30 seconds and
eliminates the four stretches of possible missed speech (20.32 s combined)
reported by the energy heuristic. Some recovered lines remain incomplete or
inaccurate. Segments can overlap a window boundary by a fraction of a second.
The spoken title is present in both hypotheses and absent from the publisher's
dialogue-only reference, so both full-episode CER figures include that penalty.

Dedicated word alignment was also tried on the full episode. It scored
27.94% CER and still reported 21.05 s of possible missed speech.

## Benchmark

The final comparison uses one fresh MLX/Metal process per profile and sample,
the existing DF-005 CER scorer, and the same audio and model in each pair.
Clean dialogue and far-field meeting recordings are regression samples.

| Sample | `df005` CER | `bounded_opening` CER | Inference seconds, baseline → bounded |
| --- | ---: | ---: | ---: |
| COERLL, full episode | 30.59% | 17.35% | 7.82 → 10.04 |
| COERLL, dialogue only | 0.59% | 5.29% | 8.56 → 9.64 |
| AliMeeting, far-field dialogue | 32.49% | 47.83% | 13.18 → 16.80 |

The dialogue-only sample also gained a 3.8 s possible-missed-speech flag.
The two regression samples score worse with fixed boundaries, so use this
profile as an explicit retry when opening dialogue is missing. A single
measurement per pair gives only an approximate latency comparison.

Full paired results are in [benchmarks/df007](../benchmarks/df007/). Reproduce
each pair with the assets prepared for DF-005 and DF-006. For example:

```sh
.venv/bin/python scripts/prepare_coerll.py --full-episode-diagnostic
.venv/bin/python scripts/benchmark_settings.py \
  data/workspace/benchmarks/coerll/coerll-ep20-full-episode.mkv \
  data/workspace/benchmarks/coerll/reference-full-episode.json \
  --name df007-final-full --profiles df005 bounded_opening --runs 1
```

Evaluation on real short films remains open. M3ED's maintainers release
annotations and features, with visual media restricted by copyright.
TMCSPEECH supplies annotations and links, with users responsible for obtaining
the media. The short-film benchmark still needs authorized Mandarin footage
and an independent dialogue reference.

- [M3ED publisher repository](https://github.com/AIM3-RUC/RUCM3ED)
- [TMCSPEECH project](https://raydonld.github.io/TMCSPEECH/)
