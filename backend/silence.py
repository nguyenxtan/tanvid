"""Energy-based silence detection for PCM16 mono 16 kHz speech audio.

This is an *energy gate*: it measures frame loudness relative to the
recording's own quiet floor. It is not a trained voice-activity detector and
cannot distinguish speech from music, laughter, or other loud non-speech.
"""

from pathlib import Path
import wave

import numpy as np

# Fixed, documented parameters. They are part of the transcription identity.
GATE = {
    'method': 'energy_gate',
    'frame_ms': 30,
    'floor_percentile': 10,
    'floor_offset_db': 12.0,
    'absolute_min_db': -60.0,
    'merge_gap_ms': 600,
    'min_region_ms': 150,
    'pad_ms': 250,
    'min_dynamic_range_db': 12.0,
    'version': 1,
}
SILENT_DB = -120.0


def frame_levels(samples, rate=16000, frame_ms=GATE['frame_ms']):
    """RMS level in dBFS for non-overlapping frames; digital silence is -120."""
    size = rate * frame_ms // 1000
    count = len(samples) // size
    if count == 0:
        return np.zeros(0)
    frames = samples[:count * size].reshape(count, size).astype(np.float64)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    with np.errstate(divide='ignore'):
        levels = 20 * np.log10(rms)
    return np.maximum(levels, SILENT_DB)


def detect_regions(levels, duration_ms, params=GATE):
    """Return non-silent [start_ms, end_ms] regions, threshold and inconclusive flag.

    Audio without enough loudness contrast (constant tone, wall-to-wall music,
    a very short clip), or non-zero audio where no region survives (e.g. quiet
    speech entirely below the absolute floor), is *inconclusive*: the whole
    duration is returned as one region. Only exact digital silence yields no
    regions. This does not protect a quiet speaker inside otherwise loud audio.
    """
    frame_ms = params['frame_ms']
    if len(levels) == 0:
        return [[0, duration_ms]], None, True
    floor = float(np.percentile(levels, params['floor_percentile']))
    threshold = max(floor + params['floor_offset_db'], params['absolute_min_db'])
    digital_silence = float(np.max(levels)) <= SILENT_DB
    if digital_silence:
        return [], round(threshold, 3), False  # Every sample is zero: nothing can be dialogue.
    if float(np.percentile(levels, 95)) - floor < params['min_dynamic_range_db']:
        return [[0, duration_ms]], round(threshold, 3), True
    regions = []
    active = None
    for index, level in enumerate(levels):
        if level >= threshold and active is None:
            active = index
        elif level < threshold and active is not None:
            regions.append([active * frame_ms, index * frame_ms])
            active = None
    if active is not None:
        regions.append([active * frame_ms, len(levels) * frame_ms])
    merged = []
    for region in regions:
        if merged and region[0] - merged[-1][1] < params['merge_gap_ms']:
            merged[-1][1] = region[1]
        else:
            merged.append(region)
    padded = []
    for start, end in merged:
        if end - start < params['min_region_ms']:
            continue
        start, end = max(0, start - params['pad_ms']), min(duration_ms, end + params['pad_ms'])
        if padded and start <= padded[-1][1]:
            padded[-1][1] = max(padded[-1][1], end)
        else:
            padded.append([start, end])
    if not padded:
        # Non-zero audio with no region (e.g. quiet speech below the absolute floor):
        # fail safe by decoding everything instead of publishing an empty transcript.
        return [[0, duration_ms]], round(threshold, 3), True
    return padded, round(threshold, 3), False


def analyze(path: Path, params=GATE):
    """Analyze a validated PCM16 mono 16 kHz WAV. Deterministic for given bytes."""
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected PCM16 mono 16kHz WAV')
        frames = wav.getnframes()
        samples = np.frombuffer(wav.readframes(frames), dtype='<i2').astype(np.float64) / 32768
    duration_ms = max(1, round(frames / 16))
    regions, threshold, inconclusive = detect_regions(frame_levels(samples, 16000, params['frame_ms']), duration_ms, params)
    speech_ms = sum(end - start for start, end in regions)
    return {'params': dict(params), 'threshold_dbfs': threshold, 'inconclusive': inconclusive, 'regions_ms': regions,
            'non_silent_ms': speech_ms, 'silent_ratio': round(1 - speech_ms / duration_ms, 6)}


def clip_timestamps(analysis):
    """Seconds list for mlx_whisper clip_timestamps; empty means nothing to decode."""
    return [value / 1000 for region in analysis['regions_ms'] for value in region]


def overlap_ms(start, end, regions):
    total = 0
    for region_start, region_end in regions:
        if region_end <= start:
            continue
        if region_start >= end:
            break
        total += min(end, region_end) - max(start, region_start)
    return total

