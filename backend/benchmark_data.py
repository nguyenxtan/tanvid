"""Read publisher annotation tiers for evaluation only, never ASR ground truth generation."""

import math
import re


class ForwardReader:
    """WAV chunk skipping over tar's forward-only compressed stream."""
    def __init__(self, source):
        self.source = source

    def read(self, size=-1):
        return self.source.read(size)

    def tell(self):
        return self.source.tell()

    def seek(self, *args):
        raise OSError('Forward-only archive member')


def parse_textgrid(text):
    tiers = re.split(r'\bitem \[\d+\]:', text)[1:]
    intervals = []
    for tier in tiers:
        name = re.search(r'\bname\s*=\s*"((?:[^"]|"")*)"', tier)
        if not name or '"IntervalTier"' not in tier:
            continue
        for match in re.finditer(r'intervals \[\d+\]:\s*xmin\s*=\s*([\d.eE+-]+)\s*xmax\s*=\s*([\d.eE+-]+)\s*text\s*=\s*"((?:[^"]|"")*)"', tier):
            start, end = float(match[1]), float(match[2])
            content = match[3].replace('""', '"').strip()
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError('Invalid annotation timing')
            if content:
                intervals.append({'start': start, 'end': end, 'speaker': name[1], 'text': content})
    if not intervals:
        raise ValueError('No publisher speech annotations parsed')
    return sorted(intervals, key=lambda s: (s['start'], s['end'], s['speaker']))


def select_excerpt(intervals, minimum=120, maximum=180):
    # Use a clean utterance boundary, fixed before seeing any hypotheses.
    candidates = [s['end'] for s in intervals if minimum <= s['end'] <= maximum
                  and not any(other['start'] < s['end'] < other['end'] for other in intervals)]
    if not candidates:
        raise ValueError('No clean 2–3 minute boundary found')
    end = max(candidates)
    selected = [s for s in intervals if s['end'] <= end]
    events = sorted([(s['start'], 1) for s in selected] + [(s['end'], -1) for s in selected])
    overlap = 0
    active = 0
    last = 0
    for timestamp, change in events:
        if active > 1:
            overlap += timestamp - last
        active += change
        last = timestamp
    return {'start_seconds': 0, 'end_seconds': end, 'duration_seconds': end,
            'speakers': sorted({s['speaker'] for s in selected}), 'overlap_seconds': overlap,
            'segments': selected, 'text': ''.join(s['text'] for s in selected)}


def parse_publisher_dialogue(pages, dialogue_number):
    """Publisher Simplified-Chinese turns of one COERLL Chinese Dialogues scene.

    `pages` is text extracted from the publisher PDF. Only the simplified section
    is read; speaker labels (e.g. ``妈：``) are kept separately from spoken text.
    Wrapped lines are joined. No characters are added, corrected or converted.
    """
    text = '\n'.join(pages)
    start = text.find('(Simplified Characters)')
    end = text.find('(Traditional Characters)')
    if start < 0 or end < start:
        raise ValueError('Simplified section not found')
    section = text[start:end]
    heading = re.search(r'^Dialogues? #%d\s*$' % dialogue_number, section, re.M)
    if not heading:
        raise ValueError('Dialogue not found')
    after = section[heading.end():]
    following = re.search(r'^Dialogues? #\d+\s*$', after, re.M)
    lines = after[:following.start()] if following else after
    turns = []
    for line in lines.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('Chinese Podcast Episode'):
            continue
        match = re.match(r'^(\S{1,6})：(.*)$', stripped)
        if match:
            turns.append({'speaker': match[1], 'text': match[2].strip()})
        elif turns and line[:1].isspace():
            turns[-1]['text'] += stripped  # Wrapped continuation of the same turn.
        else:
            raise ValueError('Unrecognized transcript line: ' + stripped)
    if not turns or any(not t['text'] for t in turns):
        raise ValueError('No publisher dialogue turns parsed')
    return turns
