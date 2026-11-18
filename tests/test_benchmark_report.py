import hashlib
import json
from pathlib import Path
import unittest

from backend.benchmark_data import parse_textgrid, select_excerpt
from backend.transcription import character_error_rate, normalize_segments

ROOT = Path(__file__).resolve().parent.parent


class RecordedBenchmarkTests(unittest.TestCase):
    def test_reference_matches_unmodified_publisher_annotation(self):
        reference=json.loads((ROOT/'benchmarks/reference.json').read_text())
        annotation=ROOT/'benchmarks/R8001_M8004.TextGrid'
        self.assertEqual(hashlib.sha256(annotation.read_bytes()).hexdigest(),reference['annotation_sha256'])
        selected=select_excerpt(parse_textgrid(annotation.read_text(encoding='utf-8-sig')))
        self.assertEqual(selected['text'],reference['text'])
        self.assertEqual(selected['duration_seconds'],156.54)
        self.assertEqual(len(selected['speakers']),4)

    def test_measured_scores_are_reproducible_from_reference(self):
        reference=json.loads((ROOT/'benchmarks/reference.json').read_text())
        report=json.loads((ROOT/'benchmarks/mlx-results.json').read_text())
        self.assertEqual(report['audio_sha256'],reference['audio_sha256'])
        self.assertEqual(len(report['measurements']),4)
        models=set()
        for row in report['measurements']:
            models.add(row['identity']['model']['repo'])
            self.assertEqual(character_error_rate(reference['text'],row['text']),row['score'])
            self.assertEqual(row['metrics']['architecture'],'arm64')
            self.assertIn('gpu',row['metrics']['device'])
            self.assertGreater(row['metrics']['peak_rss_bytes'],0)
            self.assertGreater(row['metrics']['mlx_peak_bytes'],0)
            raw=[{'start':s['start_ms']/1000,'end':s['end_ms']/1000,'text':s['original_text'],**s['confidence']} for s in row['segments']]
            self.assertEqual(normalize_segments(raw,156540),row['segments'])
        self.assertEqual(models,{'mlx-community/whisper-small-mlx','mlx-community/whisper-medium-mlx'})


if __name__=='__main__':unittest.main()
