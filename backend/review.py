"""Deterministic review flags for transcription segments.

Flags are *heuristics that request human review*. A flag is never proof that a
segment is wrong or hallucinated, and the absence of flags is never proof that
it is correct. Text and timestamps are never changed here; every flag carries
the measured evidence that triggered it.
"""

import hashlib
import re
import unicodedata

from backend.silence import overlap_ms

# Documented thresholds; part of the transcription identity via REVIEW_VERSION.
THRESHOLDS = {
    'low_avg_logprob': -1.0,          # Whisper's own fallback threshold.
    'high_no_speech_prob': 0.6,       # Whisper's own no-speech threshold; combined as Whisper does.
    'high_compression_ratio': 2.4,    # Whisper's own repetition threshold.
    'max_chars_per_second': 12.0,     # Faster than plausible Mandarin speech.
    'slow_min_duration_ms': 4000,     # Long spans with very little text...
    'min_chars_per_second': 1.0,      # ...often include silence in the timing.
    'min_non_silent_fraction': 0.1,   # Text placed over energy-gate silence.
    'repeat_unit_max_chars': 8,
    'repeat_min_occurrences': 4,
    'missed_speech_min_ms': 2000,
    'prompt_echo_min_chars': 4,       # Added after DF-006 review (single-character false positives).     # Uncovered non-silent audio worth listening to.
}
REVIEW_VERSION = 1
# Phrases widely reported as Whisper training-data artefacts on silence/music.
# Real dialogue can contain them; matching only requests review.
KNOWN_ARTEFACT_PHRASES = (
    '请不吝点赞订阅转发打赏支持明镜与点点栏目', '字幕由amaraorg社区提供', '谢谢观看', '感谢观看',
    '优优独播剧场', '中文字幕', '字幕志愿者', '请订阅', '点赞订阅',
    # Added after observing DF-006 energy-gate output on AliMeeting (disclosed in docs).
    '字幕提供', '网易云音乐',
)
DISCLAIMER = ('Review flags are heuristics that request human review. A flag is not proof of an '
              'error or hallucination; an unflagged segment is not verified correct. '
              'Original text and timestamps are unchanged.')
CATEGORIES = {
    'timestamp_clipped_to_audio_end': 'timestamp', 'overlaps_previous_segment': 'timestamp',
    'implausibly_fast_speech_rate': 'timestamp', 'long_span_little_text': 'timestamp',
    'duplicate_of_previous_segment': 'duplicate', 'repeated_text_pattern': 'suspected_hallucination',
    'high_compression_ratio': 'suspected_hallucination', 'likely_non_speech': 'suspected_hallucination',
    'text_over_detected_silence': 'suspected_hallucination', 'known_artefact_phrase': 'suspected_hallucination',
    'prompt_echo': 'suspected_hallucination', 'low_average_logprob': 'low_confidence',
}


def comparable(text):
    """Normalization used only for comparisons; never written back to text."""
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and unicodedata.category(c)[0] not in ('P', 'S'))


def segment_id(audio_sha256, raw_index, start_ms, end_ms, text):
    digest = hashlib.sha256(f'{audio_sha256}:{raw_index}:{start_ms}:{end_ms}:{text}'.encode()).hexdigest()
    return f'seg-{raw_index:04d}-{digest[:10]}'


def _repeated(text):
    limit, count = THRESHOLDS['repeat_unit_max_chars'], THRESHOLDS['repeat_min_occurrences'] - 1
    match = re.search(r'(.{1,%d}?)\1{%d,}' % (limit, count), text)
    if match and len(match.group(1)) == 1 and len(match.group(0)) < 6:
        match = None  # Allow e.g. 哈哈哈哈 / 对对对对 short single-character runs.
    return match.group(0) if match else None


def _reason(code, detail, **evidence):
    return {'code': code, 'category': CATEGORIES[code], 'heuristic': True, 'detail': detail, 'evidence': evidence}


def review_segments(entries, audio_sha256, duration_ms, silence, prompt=None):
    """entries: [(raw_index, normalized_segment, raw_end_ms)] in timeline order."""
    regions = silence['regions_ms']
    prompt_key = comparable(prompt or '')
    reviewed, previous = [], None
    for raw_index, segment, raw_end_ms in entries:
        start, end, text = segment['start_ms'], segment['end_ms'], segment['original_text']
        key, span = comparable(text), end - start
        confidence = segment['confidence']
        reasons = []
        if raw_end_ms > end:
            reasons.append(_reason('timestamp_clipped_to_audio_end', 'Model end time exceeded audio duration and was clipped',
                                   raw_end_ms=raw_end_ms, audio_duration_ms=duration_ms))
        if previous is not None and start < previous['end_ms']:
            reasons.append(_reason('overlaps_previous_segment', 'Segment starts before the previous segment ends',
                                   previous_id=previous['id'], previous_end_ms=previous['end_ms']))
        rate = len(key) / (span / 1000)
        if rate > THRESHOLDS['max_chars_per_second']:
            reasons.append(_reason('implausibly_fast_speech_rate', 'More characters than plausible for the timed span',
                                   chars_per_second=round(rate, 3)))
        if span >= THRESHOLDS['slow_min_duration_ms'] and rate < THRESHOLDS['min_chars_per_second']:
            reasons.append(_reason('long_span_little_text', 'Long timed span with little text; timing may include silence or missed speech',
                                   chars_per_second=round(rate, 3)))
        if previous is not None and key and key == comparable(previous['original_text']):
            reasons.append(_reason('duplicate_of_previous_segment', 'Same text as the previous segment (may be a real repetition)',
                                   previous_id=previous['id']))
        repeated = _repeated(key)
        if repeated:
            reasons.append(_reason('repeated_text_pattern', 'Short unit repeated many times in a row', pattern=repeated))
        ratio = confidence.get('compression_ratio')
        if ratio is not None and ratio > THRESHOLDS['high_compression_ratio']:
            reasons.append(_reason('high_compression_ratio', 'Highly repetitive token sequence', compression_ratio=ratio))
        over_silence = False
        if not silence.get('inconclusive'):
            covered = overlap_ms(start, end, regions)
            if covered / span < THRESHOLDS['min_non_silent_fraction']:
                over_silence = True
                reasons.append(_reason('text_over_detected_silence', 'Text timed over audio the energy gate measured as silent',
                                       non_silent_fraction=round(covered / span, 4)))
        # MLX Whisper's no_speech_prob is per 30 s decoding window, not per segment. Alone it
        # flagged most clean studio dialogue, so (like Whisper's own skip rule) it is combined
        # with low log-probability or measured silence.
        no_speech = confidence.get('no_speech_prob')
        logprob = confidence.get('avg_logprob')
        if (no_speech is not None and no_speech > THRESHOLDS['high_no_speech_prob']
                and (over_silence or (logprob is not None and logprob < THRESHOLDS['low_avg_logprob']))):
            reasons.append(_reason('likely_non_speech', 'High window no-speech probability with low log-probability or measured silence',
                                   no_speech_prob=no_speech, avg_logprob=logprob))
        phrase = next((p for p in KNOWN_ARTEFACT_PHRASES if p in key), None)
        if phrase:
            reasons.append(_reason('known_artefact_phrase', 'Matches a phrase commonly produced by Whisper on silence/music',
                                   phrase=phrase))
        # Short replies such as 是/中文 also occur inside the prompt; require a longer echo.
        if prompt_key and len(key) >= THRESHOLDS['prompt_echo_min_chars'] and (key in prompt_key or prompt_key in key):
            reasons.append(_reason('prompt_echo', 'Text repeats the decoding prompt'))
        if logprob is not None and logprob < THRESHOLDS['low_avg_logprob']:
            reasons.append(_reason('low_average_logprob', 'Low average token log-probability (model diagnostic, not calibrated)',
                                   avg_logprob=logprob))
        item = {'id': segment_id(audio_sha256, raw_index, start, end, text), 'raw_index': raw_index,
                **segment, 'review': {'status': 'needs_review' if reasons else 'unflagged', 'reasons': reasons}}
        reviewed.append(item)
        previous = item
    return reviewed


def missed_speech(segments, silence):
    """Non-silent audio spans with no transcript segment: possible dropped dialogue.

    Whisper can skip a whole decoding window. No per-segment flag can see text
    that was never produced, so uncovered measured sound is listed separately.
    Sound may be music/effects rather than speech; this only requests listening.
    """
    if silence.get('inconclusive'):
        return []
    spans = []
    covered = sorted((s['start_ms'], s['end_ms']) for s in segments)
    for start, end in silence['regions_ms']:
        cursor = start
        for seg_start, seg_end in covered:
            if seg_end <= cursor or seg_start >= end:
                continue
            if seg_start > cursor:
                spans.append([cursor, seg_start])
            cursor = max(cursor, seg_end)
        if cursor < end:
            spans.append([cursor, end])
    return [{'start_ms': a, 'end_ms': b, 'heuristic': True,
             'detail': 'Measured non-silent audio without any transcript segment'}
            for a, b in spans if b - a >= THRESHOLDS['missed_speech_min_ms']]


def summarize(segments, excluded, silence):
    codes, categories = {}, {}
    for segment in segments:
        for reason in segment['review']['reasons']:
            codes[reason['code']] = codes.get(reason['code'], 0) + 1
            categories[reason['category']] = categories.get(reason['category'], 0) + 1
    flagged = sum(1 for s in segments if s['review']['status'] == 'needs_review')
    missed = missed_speech(segments, silence)
    return {'possible_missed_speech': missed, 'possible_missed_speech_ms': sum(m['end_ms'] - m['start_ms'] for m in missed),
            'version': REVIEW_VERSION, 'thresholds': dict(THRESHOLDS), 'disclaimer': DISCLAIMER,
            'segments': len(segments), 'needs_review': flagged, 'unflagged': len(segments) - flagged,
            'excluded_raw_segments': len(excluded), 'reason_counts': dict(sorted(codes.items())),
            'category_counts': dict(sorted(categories.items()))}
