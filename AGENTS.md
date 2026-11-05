# Agent instructions for Roastbook/workflows

Shared GitHub Actions for Roastbook: reusable workflows (`.github/workflows/*.yml`
with `on: workflow_call`), composite actions (`.github/actions/`), Orcastrate
templates (`templates/`) that render thin caller workflows into managed
repositories, and repository settings (`scripts/repo-metadata.sh`).

## Rules

- Pin every third-party action to a full commit SHA with a `# vX.Y.Z` comment.
  Look SHAs up with `git ls-remote https://github.com/<owner>/<repo> 'refs/tags/<tag>*'`.
- Give every job explicit, minimal `permissions:`; workflows default to `permissions: {}`.
  Writes that must trigger other workflows (tags, releases, agent pull requests) use a
  GitHub App token, never a PAT.
- Reusable-workflow inputs and composite-action inputs are a public interface:
  add inputs with defaults, do not rename or remove them without bumping every caller.
  Reusable workflows load the composite actions at a pinned SHA set by
  `scripts/pin-actions.sh`: change `.github/actions/` in one commit, then run the script and
  commit the new pin (README "Pinned composite actions"). Keep action inputs backward compatible.
- Templates use Tera 2 syntax. Escape GitHub expressions as
  `${{ "{{ github.ref }}" }}`. The Roastbook/workflows commit that new callers pin is
  defined once, in `templates/_workflows-ref.yml`.
- Every template needs at least one fixture in `fixtures/`; callers in managed
  repositories must be byte-identical to `orcastrate render <file>`.
- Install tools from release binaries with a pinned `<TOOL>_VERSION` and `<TOOL>_SHA256`
  (or a version input with its `*_sha256` input), never `go run` or an unpinned download.
  Renovate bumps only the version: update every copy of the checksum in the same pull request.
- Shell with branches in a `run:` block gets a test in `tests/` that runs the block through
  `tests/workflow.py` (`step_script`) with stubbed `gh`/`npm`.
- Do not run `scripts/repo-metadata.sh` without `--dry-run` unless a maintainer asks;
  it changes live repository settings.

## Checks (CI runs the same in `.github/workflows/validate.yml`)

```sh
orcastrate validate
for f in fixtures/*.yml; do orcastrate render "$f" | actionlint -ignore 'label "ubuntu-26\.04" is unknown' -stdin-filename "$f" -; done
actionlint -ignore 'label "ubuntu-26\.04" is unknown' -ignore '^unexpected key "queue" for "concurrency" section\.'
bash scripts/pin-actions.sh --check
GIT_CLIFF=/path/to/git-cliff python3 -m unittest discover -s tests
shellcheck scripts/*.sh
```

Commits and pull request titles follow Conventional Commits.
