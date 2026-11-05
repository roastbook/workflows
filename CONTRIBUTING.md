# Contributing

This repository holds Roastbook's shared GitHub Actions: reusable workflows (`.github/workflows/*.yml` with `on: workflow_call`), composite actions (`.github/actions/`), Orcastrate templates (`templates/`) that render the caller workflows in managed repositories, and `scripts/repo-metadata.sh` for repository settings.

## Rules

- Pin every third-party action to a full commit SHA with a `# vX.Y.Z` comment.
- Give every job explicit, minimal `permissions:`; workflows default to `permissions: {}`. Writes that must trigger other workflows (tags, releases, data agent pull requests) use a GitHub App token, never a personal access token.
- Inputs of reusable workflows and composite actions are a public interface. Add inputs with defaults; do not rename or remove one without updating every caller. Reusable workflows load the composite actions from `@main`, so keep their inputs backward compatible.
- Templates use Tera syntax. Escape GitHub expressions as `${{ "{{ github.ref }}" }}`. The commit of this repository that new callers pin is defined once, in `templates/_workflows-ref.yml`.
- Every template needs a fixture in `fixtures/`. Callers in managed repositories must be byte-identical to `orcastrate render <file>`.
- `scripts/repo-metadata.sh` changes live repository settings; try it with `--dry-run` first.

## Checks

CI runs the same commands in `.github/workflows/validate.yml`:

```sh
orcastrate validate
for f in fixtures/*.yml; do orcastrate render "$f" | actionlint -ignore 'label "ubuntu-26\.04" is unknown' -stdin-filename "$f" -; done
actionlint -ignore 'label "ubuntu-26\.04" is unknown' -ignore '^unexpected key "queue" for "concurrency" section\.'
GIT_CLIFF=/path/to/git-cliff python3 -m unittest discover -s tests
shellcheck scripts/*.sh
```

Commit messages follow Conventional Commits.
