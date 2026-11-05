"""Run shell steps of the reusable workflows and templates with stubbed gh and npm."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from workflow import ROOT, run, step_script, stub

RELEASE = '.github/workflows/release.yml'
SHA = 'a' * 40


class StepTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.bin = self.path / 'bin'
        self.bin.mkdir()
        self.log = self.path / 'log'
        self.log.write_text('')
        self.summary = self.path / 'summary'
        self.summary.write_text('')

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                                        *args], cwd=self.path, text=True).strip()


class CiGateTest(StepTest):
    script = step_script(RELEASE, 'Require default branch and successful source CI')

    def gate(self, runs, ref='refs/heads/main'):
        (self.path / 'runs.json').write_text(json.dumps({'workflow_runs': runs}))
        stub(self.bin, 'gh', f'cat {self.path / "runs.json"}\n')
        return run(self.script, self.path, self.bin, GITHUB_REF=ref, DEFAULT_BRANCH='main',
                   GITHUB_SHA=SHA, GH_REPO='Roastbook/example', CI_WORKFLOW='ci.yml')

    def ci_run(self, **changes):
        return {'head_sha': SHA, 'head_repository': {'full_name': 'Roastbook/example'},
                'conclusion': 'success', **changes}

    def test_successful_run_passes(self):
        result = self.gate([self.ci_run()])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejections(self):
        for runs in ([], [self.ci_run(conclusion='failure')], [self.ci_run(conclusion=None)],
                     [self.ci_run(head_sha='b' * 40)],
                     [self.ci_run(head_repository={'full_name': 'someone/fork'})]):
            with self.subTest(runs=runs):
                result = self.gate(runs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must succeed', result.stdout)

    def test_other_branch_is_rejected(self):
        result = self.gate([self.ci_run()], ref='refs/heads/feature')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('default branch', result.stdout)


class PublishTest(StepTest):
    script = step_script(RELEASE, 'Publish release')

    def publish(self, releases, assets_glob=''):
        (self.path / 'releases.json').write_text(json.dumps(releases))
        stub(self.bin, 'gh', f'''if [[ "$1" == api ]]; then cat {self.path / "releases.json"}; exit; fi
echo "$*" >> {self.log}
[[ "$1 $2" == "release view" ]] && echo https://example.invalid/release
true
''')
        return run(self.script, self.path, self.bin, GH_REPO='Roastbook/example', TAG='v1.2.3',
                   ASSETS_GLOB=assets_glob, GITHUB_STEP_SUMMARY=str(self.summary))

    def calls(self):
        return self.log.read_text().splitlines()

    def test_missing_release_is_created(self):
        result = self.publish([{'tag_name': 'v1.2.2', 'draft': False}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0],
                         'release create v1.2.3 --verify-tag --title v1.2.3 --notes-file /tmp/release-notes.md')
        self.assertIn('https://example.invalid/release', self.summary.read_text())

    def test_draft_is_published(self):
        result = self.publish([{'tag_name': 'v1.2.3', 'draft': True}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0], 'release edit v1.2.3 --draft=false --notes-file /tmp/release-notes.md')

    def test_published_release_keeps_its_notes(self):
        result = self.publish([{'tag_name': 'v1.2.3', 'draft': False}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already published', result.stdout)
        self.assertEqual(self.calls(), ['release view v1.2.3 --json url --jq .url'])

    def test_assets_upload_files_only(self):
        (self.path / 'release/dir').mkdir(parents=True)
        (self.path / 'release/a.tgz').write_text('a')
        (self.path / 'release/b.json').write_text('b')
        result = self.publish([], assets_glob='release/*')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('release upload v1.2.3 release/a.tgz release/b.json --clobber', self.calls())

    def test_empty_glob_uploads_nothing(self):
        result = self.publish([], assets_glob='release/*')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith('release upload') for call in self.calls()))


class NpmPublishTest(StepTest):
    script = step_script(RELEASE, 'Publish unless the version exists')

    def test_publishes_in_order_and_skips_existing_versions(self):
        for i in range(11):
            package = self.path / 'packages' / str(i)
            package.mkdir(parents=True)
            (package / 'package.json').write_text(json.dumps({'name': f'@roastbook/p{i}', 'version': '1.0.0'}))
        stub(self.bin, 'npm', f'''if [[ "$1" == view ]]; then [[ "$2" == @roastbook/p1@1.0.0 ]]; exit; fi
echo "$1 $(basename "$PWD") $*" >> {self.log}
''')
        result = run(self.script, self.path, self.bin, REGISTRY='https://npm.pkg.github.com',
                     GITHUB_STEP_SUMMARY=str(self.summary))
        self.assertEqual(result.returncode, 0, result.stderr)
        published = [line.split()[1] for line in self.log.read_text().splitlines()]
        self.assertEqual(published, ['0', *map(str, range(2, 11))])
        self.assertIn('@roastbook/p1@1.0.0 is already on', self.summary.read_text())

    def test_failed_publish_stops(self):
        package = self.path / 'packages/0'
        package.mkdir(parents=True)
        (package / 'package.json').write_text('{"name": "p", "version": "1.0.0"}')
        stub(self.bin, 'npm', '[[ "$1" == view ]] && exit 1\nexit 1\n')
        result = run(self.script, self.path, self.bin, REGISTRY='r', GITHUB_STEP_SUMMARY=str(self.summary))
        self.assertNotEqual(result.returncode, 0)

    def test_missing_packages_directory_fails(self):
        result = run(self.script, self.path, self.bin, REGISTRY='r', GITHUB_STEP_SUMMARY=str(self.summary))
        self.assertNotEqual(result.returncode, 0)


class AgentPathTest(StepTest):
    script = step_script('.github/workflows/dataset-validate.yml', 'Reject changes outside the allowed paths')

    def setUp(self):
        super().setUp()
        self.git('init', '-b', 'main')
        self.write('README.md')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')

    def write(self, name):
        file = self.path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(name)

    def check(self, *files, base='origin/main'):
        for name in files:
            self.write(name)
        self.git('add', '.')
        self.git('commit', '--allow-empty', '-m', 'agent change')
        return run(self.script, self.path, BASE=base,
                   ALLOWED='datasets/coffee-places/** datasets/README.md')

    def test_allowed_paths_pass(self):
        result = self.check('datasets/coffee-places/berlin.json', 'datasets/coffee-places/de/munich.json',
                            'datasets/README.md')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_empty_change_passes(self):
        self.assertEqual(self.check().returncode, 0)

    def test_other_paths_fail(self):
        result = self.check('datasets/coffee-places/berlin.json', '.github/workflows/ci.yml', 'datasets/other.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('file=.github/workflows/ci.yml::', result.stdout)
        self.assertIn('file=datasets/other.json::', result.stdout)
        self.assertNotIn('berlin', result.stdout)

    def test_missing_base_fails(self):
        result = self.check('datasets/coffee-places/berlin.json', base='origin/missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('origin/missing is missing', result.stdout)


class BumpSchemaTest(StepTest):
    script = step_script('templates/open-coffee/bump-schema.yml', 'Rewrite $schema URLs')

    def test_rewrites_only_schema_urls(self):
        self.git('init', '-b', 'main')
        files = {
            'datasets/coffee-places/berlin.json':
                '{"$schema": "https://schema.roastbook.coffee/coffee-places.schema.v1.0.0.json", "v": "1.0.0"}',
            'datasets/roasters/x.json': '{\n  "$schema":"https://schema.roastbook.coffee/roasters.schema.v0.9.12.json"\n}',
            'datasets/other.json': '{"$schema": "https://json-schema.org/draft/2020-12/schema"}',
            'datasets/notes.txt': '"$schema": "https://schema.roastbook.coffee/x.schema.v1.0.0.json"',
        }
        for name, text in files.items():
            (self.path / name).parent.mkdir(parents=True, exist_ok=True)
            (self.path / name).write_text(text)
        self.git('add', '.')
        self.git('commit', '-m', 'datasets')
        output = self.path / 'output'
        output.write_text('')
        result = run(self.script, self.path, VERSION='1.2.3', GITHUB_OUTPUT=str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        read = lambda name: (self.path / name).read_text()
        self.assertEqual(read('datasets/coffee-places/berlin.json'),
                         '{"$schema": "https://schema.roastbook.coffee/coffee-places.schema.v1.2.3.json", "v": "1.0.0"}')
        self.assertIn('"$schema":"https://schema.roastbook.coffee/roasters.schema.v1.2.3.json"',
                      read('datasets/roasters/x.json'))
        self.assertEqual(read('datasets/other.json'), files['datasets/other.json'])
        self.assertEqual(read('datasets/notes.txt'), files['datasets/notes.txt'])
        self.assertEqual(output.read_text(), 'files<<CHANGED_FILES\n- `datasets/coffee-places/berlin.json`\n'
                         '- `datasets/roasters/x.json`\nCHANGED_FILES\n')


class ToolPinTest(unittest.TestCase):
    """Every copy of a release-binary pin names the same version and checksum."""

    PINS = {
        'actionlint': [r'ACTIONLINT_VERSION: (v\S+)\n\s+ACTIONLINT_SHA256: (\w+)'],
        'git-cliff': [r'GIT_CLIFF_VERSION: (v\S+)\n\s+GIT_CLIFF_SHA256: (\w+)',
                      r'git_cliff_version:[^\n]*\n(?:\s+\w+:[^\n]*\n)*?\s+default: (\S+)\n\s+git_cliff_sha256:'
                      r'[^\n]*\n(?:\s+\w+:[^\n]*\n)*?\s+default: (\w+)'],
        'lychee': [r'LYCHEE_VERSION: (lychee-v\S+)\n\s+LYCHEE_SHA256: (\w+)',
                   r'lychee_version:[^\n]*\n(?:\s+\w+:[^\n]*\n)*?\s+default: (\S+)\n\s+lychee_sha256:'
                   r'[^\n]*\n(?:\s+\w+:[^\n]*\n)*?\s+default: (\w+)'],
        'orcastrate': [r'ORCASTRATE_VERSION: (v\S+)\n\s+ORCASTRATE_SHA256: (\w+)'],
    }

    def test_pins_agree(self):
        text = '\n'.join(path.read_text() for path in sorted((ROOT / '.github/workflows').glob('*.yml')))
        for tool, patterns in self.PINS.items():
            with self.subTest(tool=tool):
                found = [re.findall(pattern, text) for pattern in patterns]
                self.assertTrue(all(found), f'a {tool} pattern matches nothing')
                pins = {pin for matches in found for pin in matches}
                self.assertEqual(len(pins), 1, pins)
                self.assertRegex(next(iter(pins))[1], '^[0-9a-f]{64}$')
        # Every pinned version is next to its checksum: no unpaired copies.
        for name in ('ACTIONLINT', 'GIT_CLIFF', 'LYCHEE', 'ORCASTRATE'):
            self.assertEqual(text.count(f'{name}_VERSION:'), text.count(f'{name}_SHA256:'), name)


if __name__ == '__main__':
    unittest.main()
