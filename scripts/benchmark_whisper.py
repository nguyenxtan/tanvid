#!/usr/bin/env python3
"""Fresh-process comparison on one frozen, independently annotated excerpt."""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.audio import checksum
from backend.media import MediaService
from backend.transcription import character_error_rate
from backend.workspace import Workspace, WorkspaceConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--runs', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error('Choose 1–5 measured fresh-process runs per model')
    reference = json.loads(args.reference.read_text())
    workspace = Workspace(WorkspaceConfig.from_env())
    service = MediaService(workspace)
    audio = service.extract_audio(args.video)['speech']
    if checksum(Path(audio['path'])) != reference['audio_sha256']:
        raise ValueError('Audio does not match the frozen reference provenance')
    measurements = []
    # Alternate order to reduce simple order/thermal confounding.
    for iteration in range(args.runs):
        for model in (('small', 'medium') if iteration % 2 == 0 else ('medium', 'small')):
            print(f'Benchmark {model}, fresh process run {iteration + 1}', file=sys.stderr, flush=True)
            result = service.transcribe(args.video, model=model, force=True)
            result['score'] = character_error_rate(reference['text'], result['text'])
            result['run'] = iteration + 1
            measurements.append(result)
            portable = [{key: value for key, value in row.items() if key != 'result_path'} for row in measurements]
            report = {'audio_sha256': audio['sha256'], 'reference_sha256': checksum(args.reference),
                      'sample_duration_seconds': audio['duration_seconds'], 'measurements': portable}
            encoded = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
            with workspace.locked():
                workspace.preflight(len(encoded))
                target = workspace.root / 'benchmarks' / 'mlx-benchmark.json'
                target.parent.mkdir(exist_ok=True)
                pending = target.with_suffix('.pending')
                pending.write_bytes(encoded)
                pending.replace(target)
            print(json.dumps({'model': model, 'run': iteration + 1, 'metrics': result['metrics'],
                              'cer': result['score']['cer'], 'end_to_end_seconds': result['elapsed_seconds']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
