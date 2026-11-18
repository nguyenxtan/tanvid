#!/usr/bin/env python3
"""Prepare the UT Austin COERLL Chinese Dialogues episode 20 benchmark sample.

Audio and the publisher's human-written transcript PDF are downloaded from the
publisher's official public folder by pinned file ID, size bound and SHA-256.
The reference is the publisher's Simplified-Chinese text of Dialogue #70; it is
never generated or edited from ASR output.

The episode opens with a spoken English title ("Episode 20 ... Dialogue 70")
that is not part of the publisher's dialogue text. The excerpt therefore starts
at a fixed cut inside the silence before the first turn and runs, unedited, to
the end of the episode. The cut must measure as silent or preparation fails.
"""

import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from pypdf import PdfReader

from backend.audio import checksum
from backend.benchmark_data import parse_publisher_dialogue
from backend.media import MediaService
from backend import silence
from backend.workspace import Workspace, WorkspaceConfig

DOWNLOAD = 'https://drive.google.com/uc?export=download&id='
FILES = {
    'chinese-dialogues-ep20.mp3': {'id': '1YqeiRJKchLceHSYiKd34h59Kec3KY9ry', 'size_bytes': 1307804,
                                   'sha256': '6dd9918ade3f97d01e2eb7a98ef73396ff8c668b1c6612a2f280bcc0320d4ab0'},
    'chinese-dialogues-ep20.pdf': {'id': '1-jcslfLah9o9JTtlmVEQGmNcUGfFGyjP', 'size_bytes': 283860,
                                   'sha256': '8911f208e4656f33cc72b94c2d19f46488c0c9c6e3aa551925647332959801e4'},
}
DIALOGUE = 70
# Quietest 10 ms frame between the spoken title (ends ~5.35 s) and the first
# turn (onset ~6.55 s), from energy analysis of the decoded episode audio.
START_SECONDS = 5.95


def fetch(name, item, directory):
    target = directory / name
    if target.is_file() and checksum(target) == item['sha256']:
        return target
    pending = target.with_suffix(target.suffix + '.part')
    count = 0
    try:
        with urllib.request.urlopen(DOWNLOAD + item['id'], timeout=60) as response, pending.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > item['size_bytes']:
                    raise ValueError(name + ' exceeded its pinned size')
                output.write(chunk)
        if count != item['size_bytes'] or checksum(pending) != item['sha256']:
            raise ValueError(name + ' does not match its pinned size/SHA-256')
    except BaseException:
        pending.unlink(missing_ok=True)  # Never leave quota-counted partial downloads.
        raise
    pending.replace(target)
    return target


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-episode-diagnostic', action='store_true',
                        help='Also build the untrimmed episode video (title included) used only for the '
                             'DF-006 window-skip diagnostic; scored with benchmarks/coerll/reference-full-episode.json')
    args = parser.parse_args()
    workspace = Workspace(WorkspaceConfig.from_env())
    with workspace.locked():
        workspace.preflight(sum(f['size_bytes'] for f in FILES.values()) + 64 * 1024**2)
        directory = workspace.root / 'benchmarks' / 'coerll'
        directory.mkdir(parents=True, exist_ok=True)
        mp3 = fetch('chinese-dialogues-ep20.mp3', FILES['chinese-dialogues-ep20.mp3'], directory)
        pdf = fetch('chinese-dialogues-ep20.pdf', FILES['chinese-dialogues-ep20.pdf'], directory)
        turns = parse_publisher_dialogue([page.extract_text() for page in PdfReader(pdf).pages], DIALOGUE)
        duration = float(json.loads(subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(mp3)],
            check=True, capture_output=True, timeout=15).stdout)['format']['duration'])
        pcm = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(mp3), '-ac', '1', '-ar', '16000',
                              '-f', 's16le', '-'], check=True, capture_output=True, timeout=60).stdout
        levels = silence.frame_levels(np.frombuffer(pcm, '<i2') / 32768, 16000, 10)
        cut = round(START_SECONDS * 100)
        if max(levels[cut - 10:cut + 10]) > -45:
            raise ValueError('Fixed excerpt cut is not inside measured silence')
        excerpt = duration - START_SECONDS
        video = directory / 'coerll-ep20-dialogue70.mkv'
        # Trim the spoken title; black video wrapper only, to exercise the existing pipeline.
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(mp3),
                        '-f', 'lavfi', '-i', f'color=c=black:s=160x120:r=25:d={excerpt}',
                        '-map', '1:v', '-map', '0:a', '-af', f'atrim=start={START_SECONDS},asetpts=PTS-STARTPTS',
                        '-t', str(excerpt), '-c:v', 'libx264', '-c:a', 'pcm_s16le', str(video)], check=True, timeout=60)
        if args.full_episode_diagnostic:
            subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(mp3),
                            '-f', 'lavfi', '-i', f'color=c=black:s=160x120:r=25:d={duration}',
                            '-map', '1:v', '-map', '0:a', '-t', str(duration), '-c:v', 'libx264', '-c:a', 'pcm_s16le',
                            str(directory / 'coerll-ep20-full-episode.mkv')], check=True, timeout=60)
    reference = {
        'sample': 'coerll-chinese-dialogues-ep20-dialogue70',
        'title': 'Chinese Dialogues, Episode #20, Dialogue #70 (family scene, three speakers)',
        'author': 'Wen-Hua Teng', 'publisher': 'COERLL, The University of Texas at Austin',
        'source_url': 'https://coerll.utexas.edu/coerll/oer/chinese-dialogues-podcast/',
        'folder_url': 'https://drive.google.com/drive/folders/1NBFhcdv83ltni8fwhU7iLHpEmFzxCFbO',
        'license': 'CC-BY (publisher resource page; version not stated on the resource; site badge links CC BY 4.0)',
        'files': {name: dict(item, url=DOWNLOAD + item['id']) for name, item in FILES.items()},
        'dialogue': DIALOGUE, 'speakers': sorted({t['speaker'] for t in turns}),
        'source_duration_seconds': duration, 'start_seconds': START_SECONDS, 'end_seconds': duration,
        'duration_seconds': round(excerpt, 6),
        'turns': turns, 'text': ''.join(t['text'] for t in turns),
        'reference_origin': 'Publisher human-written transcript PDF (Simplified section), no ASR-generated ground truth',
        'adaptation': f'Removed the spoken English episode/dialogue title (0-{START_SECONDS} s, cut in measured '
                      'silence); remainder of the episode unedited; black video wrapper only; '
                      'speaker labels removed from scored text; wrapped PDF lines joined',
        'video_sha256': checksum(video),
    }
    audio = MediaService(workspace).extract_audio(video)['speech']
    reference['audio_sha256'] = audio['sha256']
    with workspace.locked():
        workspace.preflight(1024**2)
        (directory / 'reference.json').write_text(json.dumps(reference, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in reference.items() if k not in ('turns', 'text')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
