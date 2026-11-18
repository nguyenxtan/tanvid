#!/usr/bin/env python3
"""Prepare one preselected AliMeeting far-field excerpt and its original reference."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import wave

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.audio import checksum
from backend.benchmark_data import ForwardReader, parse_textgrid, select_excerpt
from backend.media import MediaService
from backend.workspace import Workspace, WorkspaceConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    workspace = Workspace(WorkspaceConfig.from_env())
    archive_path = args.archive or workspace.root / 'benchmarks' / 'Eval_Ali.tar.gz'
    session = 'R8001_M8004'
    with workspace.locked():
        workspace.preflight(128 * 1024**2)
        directory = workspace.root / 'benchmarks' / 'alimeeting'
        directory.mkdir(parents=True, exist_ok=True)
        source_wave = directory / 'far-first-180s.wav'
        annotations = []
        with tarfile.open(archive_path, 'r|gz') as archive:
            for member in archive:
                if not member.isfile():
                    continue
                name = Path(member.name).name
                if '/Eval_Ali_far/' in member.name and name == session + '_MS801.wav':
                    with archive.extractfile(member) as raw, wave.open(ForwardReader(raw), 'rb') as source:
                        if source.getframerate() != 16000 or source.getsampwidth() != 2:
                            raise ValueError('Unexpected official audio format')
                        # Keep original channels here; select only channel 0 during wrapping.
                        with wave.open(str(source_wave), 'wb') as output:
                            output.setparams(source.getparams())
                            output.writeframes(source.readframes(180 * source.getframerate()))
                elif name.startswith(session) and name.endswith('.TextGrid') and '/Eval_Ali_far/' in member.name:
                    if member.size > 1024**2:
                        raise ValueError('Unexpectedly large reference annotation')
                    raw = archive.extractfile(member).read()
                    try:
                        text = raw.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        text = raw.decode('utf-16')
                    (directory / name).write_bytes(raw)
                    annotations.append((member.name, name, text))
        if len(annotations) != 1 or not source_wave.exists():
            raise ValueError('Expected exactly one official far-field annotation and audio match: ' + str([a[0] for a in annotations]))
        reference = select_excerpt(parse_textgrid(annotations[0][2]))
        video = directory / 'mandarin-dialogue.mkv'
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(source_wave),
                        '-f', 'lavfi', '-i', f"color=c=black:s=160x120:r=100:d={reference['duration_seconds']}",
                        '-map', '1:v', '-map', '0:a', '-af', 'pan=mono|c0=c0',
                        '-t', str(reference['duration_seconds']), '-c:v', 'libx264', '-c:a', 'pcm_s16le', str(video)],
                       check=True, timeout=60)
        reference.update(source_url='https://www.openslr.org/119/',
                         download_url='https://speech-lab-share-data.oss-cn-shanghai.aliyuncs.com/AliMeeting/openlr/Eval_Ali.tar.gz',
                         license='CC-BY-SA-4.0', attribution='AliMeeting / Alibaba Group; Fan Yu et al., M2MeT (ICASSP 2022)',
                         annotation_member=annotations[0][0], annotation_sha256=checksum(directory / annotations[0][1]),
                         archive_sha256=checksum(archive_path), video_sha256=checksum(video),
                         source_channel=0, reference_origin='Publisher human reference, no ASR-generated ground truth',
                         adaptation='Excerpt from start to last clean utterance boundary <=180s, first far-field microphone; black video wrapper only')
    # The extraction pipeline owns its own lock.
    audio = MediaService(workspace).extract_audio(video)['speech']
    reference['audio_sha256'] = audio['sha256']
    with workspace.locked():
        workspace.preflight(1024**2)
        (directory / 'reference.json').write_text(json.dumps(reference, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in reference.items() if key not in ('text', 'segments')}, ensure_ascii=False, indent=2))
    print('Reference preview:', reference['text'][:250])


if __name__ == '__main__':
    main()
