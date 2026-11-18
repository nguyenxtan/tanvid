#!/usr/bin/env python3
"""Fresh-process decoding-profile comparison on one frozen, publisher-referenced sample.

Uses the identical audio, model and DF-005 CER scoring for every profile.
Profile order rotates between runs to reduce simple order/thermal confounding.
Every full result (raw inference, normalized segments, review flags) is kept.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.audio import checksum
from backend.media import MediaService
from backend.transcription import PROFILES, character_error_rate
from backend.workspace import Workspace, WorkspaceConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--name', required=True, help='Report name, e.g. alimeeting or coerll')
    parser.add_argument('--model', default='medium', choices=('small', 'medium'))
    parser.add_argument('--profiles', nargs='+', default=list(PROFILES), choices=list(PROFILES))
    parser.add_argument('--runs', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error('Choose 1–5 measured fresh-process runs per profile')
    reference = json.loads(args.reference.read_text())
    workspace = Workspace(WorkspaceConfig.from_env())
    service = MediaService(workspace)
    audio = service.extract_audio(args.video)['speech']
    if checksum(Path(audio['path'])) != reference['audio_sha256']:
        raise ValueError('Audio does not match the frozen reference provenance')
    measurements = []
    for iteration in range(args.runs):
        shift = iteration % len(args.profiles)
        for profile in args.profiles[shift:] + args.profiles[:shift]:
            print(f'Benchmark {args.model}/{profile}, fresh process run {iteration + 1}', file=sys.stderr, flush=True)
            result = service.transcribe(args.video, model=args.model, force=True, profile=profile)
            result.pop('result_path')
            result['score'] = character_error_rate(reference['text'], result['text'])
            result['run'] = iteration + 1
            measurements.append(result)
            report = {'name': args.name, 'audio_sha256': audio['sha256'], 'reference_sha256': checksum(args.reference),
                      'sample_duration_seconds': audio['duration_seconds'], 'model': args.model,
                      'profiles': {p: PROFILES[p]['description'] for p in args.profiles}, 'measurements': measurements}
            encoded = (json.dumps(report, indent=1, ensure_ascii=False, allow_nan=False) + '\n').encode()
            with workspace.locked():
                workspace.preflight(len(encoded))
                target = workspace.root / 'benchmarks' / f'df006-{args.name}.json'
                pending = target.with_suffix('.pending')
                pending.write_bytes(encoded)
                pending.replace(target)
            print(json.dumps({'profile': profile, 'run': iteration + 1, 'cer': result['score']['cer'],
                              'edits': result['score']['edits'], 'inference_seconds': result['metrics']['inference_seconds'],
                              'needs_review': result['review']['needs_review'], 'segments': result['review']['segments']},
                             ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
