"""Verifier failure modes using isolated Git fixtures and explicit inventories."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.verify import run_verification, source_manifest


def fixture_case(name, action=lambda: None):
    class Case(unittest.TestCase):
        def id(self):
            return name

        def runTest(self):
            action()
    return Case()


class FixtureLoader:
    def __init__(self, suite, errors=None):
        self.suite = suite
        self.errors = errors or []

    def discover(self, path):
        return self.suite


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'tests').mkdir()
        (self.root / 'source.py').write_text('VALUE = 1\n')
        (self.root / '.gitignore').write_text('runtime/\n')
        self.inventory = self.root / 'tests/expected_inventory.json'
        self.inventory.write_text(json.dumps(['fixture.test_one']))
        for arguments in (['init', '--quiet'], ['add', '.'],
                          ['-c', 'user.name=Evidence Fixture', '-c', 'user.email=fixture@example.invalid',
                           'commit', '--quiet', '-m', 'fixture']):
            subprocess.run(['git', *arguments], cwd=self.root, check=True, capture_output=True)

    def verify(self, cases=None, loader=None):
        suite = unittest.TestSuite(cases if cases is not None else [fixture_case('fixture.test_one')])
        evidence = run_verification(self.root, self.root / 'runtime/evidence',
                                    loader=loader or FixtureLoader(suite))
        persisted = json.loads((self.root / 'runtime/evidence/evidence.json').read_text())
        self.assertEqual(evidence, persisted)
        return evidence

    def test_clean_complete_run_records_inventory_manifest_and_transcript(self):
        evidence = self.verify([fixture_case('fixture.test_one', lambda: print('observed output'))])
        self.assertTrue(evidence['successful'])
        self.assertFalse(evidence['git_before']['dirty'])
        self.assertEqual(evidence['discovered_test_ids'], ['fixture.test_one'])
        self.assertEqual(evidence['executed_test_ids'], ['fixture.test_one'])
        transcript = (self.root / 'runtime/evidence/transcript.txt').read_bytes()
        self.assertIn(b'observed output', transcript)
        self.assertEqual(evidence['transcript_sha256'], hashlib.sha256(transcript).hexdigest())
        self.assertEqual(evidence['source_before'], evidence['source_after'])
        self.assertNotIn(str(self.root), json.dumps(evidence['source_before']))

    def test_dirty_worktree_is_recorded_and_stable_development_run_is_allowed(self):
        (self.root / 'source.py').write_text('VALUE = 2\n')
        evidence = self.verify()
        self.assertTrue(evidence['successful'])
        self.assertTrue(evidence['git_before']['dirty'])
        self.assertTrue(evidence['source_unchanged'])

    def test_require_clean_rejects_dirty_ci_run(self):
        (self.root / 'source.py').write_text('VALUE = 2\n')
        evidence = run_verification(self.root, self.root / 'runtime/evidence',
                                    loader=FixtureLoader(unittest.TestSuite([fixture_case('fixture.test_one')])),
                                    require_clean=True)
        self.assertFalse(evidence['successful'])
        self.assertIn('A clean Git worktree is required for this run', evidence['validation_errors'])

    def test_branch_movement_fails_even_when_source_and_commit_are_identical(self):
        def move_branch():
            subprocess.run(['git', 'checkout', '--quiet', '-b', 'fixture-moved'],
                           cwd=self.root, check=True, capture_output=True)
        evidence = self.verify([fixture_case('fixture.test_one', move_branch)])
        self.assertFalse(evidence['successful'])
        self.assertTrue(evidence['source_unchanged'])
        self.assertEqual(evidence['git_before']['commit'], evidence['git_after']['commit'])
        self.assertIn('Git branch changed during verification', evidence['validation_errors'])

    def test_git_status_drift_fails_even_when_source_manifest_is_unchanged(self):
        evidence = self.verify([fixture_case('fixture.test_one',
                                  lambda: (self.root / 'untracked.txt').write_text('unexpected'))])
        self.assertFalse(evidence['successful'])
        self.assertTrue(evidence['source_unchanged'])
        self.assertIn('Git worktree status changed during verification', evidence['validation_errors'])

    def test_source_mutation_during_execution_fails(self):
        evidence = self.verify([fixture_case('fixture.test_one',
                          lambda: (self.root / 'source.py').write_text('VALUE = 3\n'))])
        self.assertFalse(evidence['successful'])
        self.assertFalse(evidence['source_unchanged'])
        self.assertIn('Source manifest changed during verification', evidence['validation_errors'])

    def test_skip_is_failure_even_when_unittest_would_succeed(self):
        def skip():
            raise unittest.SkipTest('unexpected optional dependency')
        evidence = self.verify([fixture_case('fixture.test_one', skip)])
        self.assertFalse(evidence['successful'])
        self.assertEqual(evidence['skipped'], 1)
        self.assertEqual(evidence['skip_details'][0]['reason'], 'unexpected optional dependency')

    def test_empty_discovery_fails(self):
        evidence = self.verify([])
        self.assertFalse(evidence['successful'])
        self.assertEqual(evidence['tests_run'], 0)

    def test_incomplete_discovery_fails_exact_inventory(self):
        self.inventory.write_text(json.dumps(['fixture.test_one', 'fixture.test_two']))
        evidence = self.verify()
        self.assertFalse(evidence['successful'])
        self.assertIn('Discovered inventory differs from explicit expected inventory', evidence['validation_errors'])

    def test_collection_error_is_persisted_even_if_discovered_test_passes(self):
        loader = FixtureLoader(unittest.TestSuite([fixture_case('fixture.test_one')]),
                               ['ImportError: simulated missing import'])
        evidence = self.verify(loader=loader)
        self.assertFalse(evidence['successful'])
        self.assertEqual(evidence['collection_errors'], ['ImportError: simulated missing import'])

    def test_discovery_exception_still_has_before_and_after_manifests(self):
        class BrokenLoader:
            errors = []

            def discover(self, path):
                raise ImportError('collection exploded')
        evidence = self.verify(loader=BrokenLoader())
        self.assertFalse(evidence['successful'])
        self.assertTrue(evidence['source_unchanged'])
        self.assertIn('collection exploded', evidence['collection_errors'][0])

    def test_partial_execution_fails_count_and_ids(self):
        class PartialSuite(unittest.TestSuite):
            def run(self, result, debug=False):
                list(self)[0](result)
                return result
        self.inventory.write_text(json.dumps(['fixture.test_one', 'fixture.test_two']))
        suite = PartialSuite([fixture_case('fixture.test_one'), fixture_case('fixture.test_two')])
        evidence = self.verify(loader=FixtureLoader(suite))
        self.assertFalse(evidence['successful'])
        self.assertEqual(evidence['tests_run'], 1)
        self.assertIn('Executed inventory/count differs from discovery or expected inventory', evidence['validation_errors'])

    def test_missing_inventory_never_silently_creates_one(self):
        self.inventory.unlink()
        evidence = self.verify()
        self.assertFalse(evidence['successful'])
        self.assertFalse(self.inventory.exists())
        self.assertTrue(evidence['source_unchanged'])

    def test_runtime_and_venv_outputs_do_not_change_source_manifest(self):
        before = source_manifest(self.root)
        for directory in ('runtime', '.venv', 'docs'):
            path = self.root / directory
            path.mkdir()
            (path / 'generated.py').write_text('generated')
        self.assertEqual(before, source_manifest(self.root))

    def test_reusing_evidence_directory_is_rejected(self):
        self.verify()
        with self.assertRaises(ValueError):
            run_verification(self.root, self.root / 'runtime/evidence')
