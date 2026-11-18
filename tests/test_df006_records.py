import hashlib
import json
from pathlib import Path
import unittest

from pypdf import PdfReader

from backend.benchmark_data import parse_publisher_dialogue
from backend.transcription import PROFILES, build_review, character_error_rate

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / 'benchmarks' / 'df006'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    return json.loads((RECORDS / f'df006-{name}.json').read_text())


class CoerllReferenceTests(unittest.TestCase):
    def test_reference_is_exact_publisher_pdf_text(self):
        reference = json.loads((ROOT / 'benchmarks/coerll/reference.json').read_text())
        pdf = ROOT / 'benchmarks/coerll/chinese-dialogues-ep20.pdf'
        self.assertEqual(sha(pdf), reference['files']['chinese-dialogues-ep20.pdf']['sha256'])
        turns = parse_publisher_dialogue([page.extract_text() for page in PdfReader(pdf).pages], 70)
        self.assertEqual(turns, reference['turns'])
        self.assertEqual(reference['text'], ''.join(t['text'] for t in turns))
        self.assertEqual((len(turns), reference['speakers']), (21, ['中', '妈', '爸']))
        self.assertTrue(reference['text'].startswith('小中，爸爸回家了没有？'))
        self.assertEqual((reference['start_seconds'], reference['end_seconds']), (5.95, 130.56))
        self.assertIn('CC-BY', reference['license'])

    def test_full_episode_diagnostic_reference_has_identical_text(self):
        primary = json.loads((ROOT / 'benchmarks/coerll/reference.json').read_text())
        full = json.loads((ROOT / 'benchmarks/coerll/reference-full-episode.json').read_text())
        self.assertEqual((full['text'], full['turns']), (primary['text'], primary['turns']))
        self.assertIn('DIAGNOSTIC ONLY', full['adaptation'])

    def test_parser_rejects_unknown_dialogue_and_layout(self):
        with self.assertRaises(ValueError):
            parse_publisher_dialogue(['Chinese Podcast Episode #1 (Simplified Characters)\nDialogue #1\nA：你好\n'
                                      '(Traditional Characters)'], 2)
        with self.assertRaises(ValueError):
            parse_publisher_dialogue(['(Simplified Characters)\nDialogue #1\nunlabelled line\n(Traditional Characters)'], 1)


class Df006RecordTests(unittest.TestCase):
    def test_df005_original_records_are_unchanged(self):
        self.assertEqual(sha(ROOT / 'benchmarks/mlx-results.json'),
                         '3bd836f8a595f7be6ef565aa671b9e49559b3fb96abff149a55c55aef8148db3')
        self.assertEqual(sha(ROOT / 'benchmarks/reference.json'),
                         '2ac2eb2b32c3cd8492c6b81eb5723e14f35984f59e932aaa396bd386f3c31498')

    def test_scores_and_reviews_reproduce_from_raw_records(self):
        references = {'alimeeting': ROOT / 'benchmarks/reference.json',
                      'coerll': ROOT / 'benchmarks/coerll/reference.json',
                      'coerll-small': ROOT / 'benchmarks/coerll/reference.json',
                      'coerll-full-episode': ROOT / 'benchmarks/coerll/reference-full-episode.json'}
        for name, path in references.items():
            reference = json.loads(path.read_text())
            report = load(name)
            self.assertEqual(report['audio_sha256'], reference['audio_sha256'])
            self.assertNotIn('/Users/', json.dumps(report))
            for row in report['measurements']:
                with self.subTest(name=name, profile=row['identity']['profile'], run=row['run']):
                    self.assertEqual(character_error_rate(reference['text'], row['text']), row['score'])
                    adjustments = {}
                    segments, excluded, summary = build_review(row['raw_inference']['segments'], row['identity'],
                                                               row['duration_ms'], row['silence'], adjustments)
                    # Records predate review-fix thresholds that were only *added* (prompt_echo_min_chars);
                    # every recorded threshold is unchanged and every recorded flag re-derives exactly.
                    recorded = dict(row['review'])
                    current = dict(summary)
                    old_thresholds, new_thresholds = recorded.pop('thresholds'), current.pop('thresholds')
                    self.assertEqual({k: new_thresholds[k] for k in old_thresholds}, old_thresholds)
                    self.assertEqual(set(new_thresholds) - set(old_thresholds), {'prompt_echo_min_chars'})
                    self.assertEqual((segments, excluded, current, adjustments),
                                     (row['segments'], row['excluded_raw_segments'], recorded,
                                      row['segment_adjustments']))
                    self.assertEqual(row['identity']['options'], json.loads(json.dumps(PROFILES[row['identity']['profile']]['options'])))
                    self.assertIn('gpu', row['metrics']['device'])

    def test_df005_profile_reproduces_df005_alimeeting_result(self):
        original = json.loads((ROOT / 'benchmarks/mlx-results.json').read_text())
        medium = next(r for r in original['measurements'] if 'medium' in r['identity']['model']['repo'])
        for row in load('alimeeting')['measurements']:
            if row['identity']['profile'] == 'df005':
                self.assertEqual(row['text'], medium['text'])
                self.assertEqual(row['score']['edits'], 269)
                self.assertEqual(row['identity']['model'], medium['identity']['model'])

    def test_measured_conclusions_documented(self):
        def edits(name, profile):
            return {r['score']['edits'] for r in load(name)['measurements'] if r['identity']['profile'] == profile}
        self.assertEqual(edits('coerll', 'df005'), {2})
        self.assertEqual(edits('alimeeting', 'energy_gate'), {537})
        self.assertEqual(edits('coerll', 'energy_gate'), {58})
        full = [r for r in load('coerll-full-episode')['measurements'] if r['identity']['profile'] == 'df005']
        self.assertTrue(all(r['review']['possible_missed_speech_ms'] > 20000 for r in full))
        self.assertTrue(all(r['review']['needs_review'] == 0 for r in full))


if __name__ == '__main__':
    unittest.main()
