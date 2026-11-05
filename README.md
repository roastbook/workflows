# Roastbook workflows

Shared GitHub Actions for [Roastbook](https://github.com/Roastbook) repositories:
reusable workflows, composite actions, and the [Orcastrate](https://github.com/michidk/orcastrate)
templates that keep a thin caller workflow in every managed repository up to date.

Managed repositories never copy CI logic. Each one has small caller files such as
`.github/workflows/cupping.yml` that start with Orcastrate frontmatter and call a
reusable workflow from this repository at a pinned commit:

```yaml
# @orcastrate
# template: open-coffee/cupping
# params:
#   kind: data
# @end-orcastrate

name: Roastbook · ☕ Cupping (validate)
# …
    uses: Roastbook/workflows/.github/workflows/dataset-validate.yml@<sha> # main
```

## Reusable workflows

All live in `.github/workflows/`, run on `ubuntu-26.04`, and set minimal per-job
permissions. They call the repository's own scripts, so CI and local runs behave
the same way.

| Workflow | Runs | Inputs (default) |
|---|---|---|
| `schema-validate.yml` | `scripts/validate.sh` with `BASE_REF` set to the pull request base, plus actionlint | `actionlint` (true), `timeout_minutes` (15) |
| `dataset-validate.yml` | as above, plus the bot path rule: pull requests opened by `bot_login` may only change `bot_allowed_paths` | `bot_login` (`roastbook-sourcing[bot]`), `bot_allowed_paths` (`datasets/coffee-places/**`), `actionlint` (true), `timeout_minutes` (15) |
| `site-build.yml` | `scripts/build.sh`; pull requests upload a `site-preview-pr-<n>` artifact, other events the Pages artifact | `dist` (`dist`), `preview_retention_days` (7), `timeout_minutes` (20) |
| `pages-deploy.yml` | `actions/deploy-pages` into environment `github-pages`, concurrency group `pages` | none; output `page_url` |
| `link-check.yml` | lychee via `scripts/link-check.sh` (warn-only on pull requests, `--full` and failing otherwise) and HTTP smoke checks on scheduled and manual runs | `link_check` (true), `full` (false), `smoke_urls` (""), `lychee_version`, `timeout_minutes` (30) |
| `release.yml` | the release flow below | see below |
| `agent-run.yml` | `scripts/agent.sh` as the Sourcing App, with `.cache/crawl` cached between runs | `app_id`, `llm_base_url`, `llm_model`, `budget_usd` (all required), `timeout_minutes` (180); secrets `app_private_key`, `llm_api_key` |

Every job that runs a script ends with the `roast-report` action, which turns
`.roast/report.json` into a "☕ Roast report" in the job summary.

### Release

`release.yml` is the shared release implementation for every repository. The
caller starts it with `workflow_dispatch` on the default branch. It:

1. requires a successful push run of `ci_workflow` for this exact commit;
2. computes the next version: `semver` asks git-cliff for the bump from
   Conventional Commits (or applies the explicit `bump_type`); `date` uses
   `YYYY.MM.DD.N` for today in UTC (`.1`, then `.2` the same day);
3. stops without releasing when `bump_type` is `auto` and there are no
   unreleased Conventional Commits, reuses an existing tag on the same commit,
   and refuses tags that go backwards or point elsewhere;
4. tags the tested commit and creates or publishes the GitHub Release with
   git-cliff notes, using the releaser App so tag and release events trigger
   other workflows (for example the Pages deploy on tags).

Optional hooks, all off by default:

| Input | Default | Effect |
|---|---|---|
| `bump_type` | `auto` | `auto`, `patch`, `minor` or `major` |
| `ci_workflow` | `ci.yml` | workflow file that must have passed |
| `version_scheme` | `semver` | `semver` (`vX.Y.Z`) or `date` (`YYYY.MM.DD.N`) |
| `cliff_config`, `git_cliff_version` | `cliff.toml`, `v2.14.2` | git-cliff configuration and release |
| `node_setup` | false | run the `setup` action (Bun, `bun install`) before the assets command |
| `assets_command` | "" | shell command with `TAG` and `VERSION` set, e.g. `scripts/release-assets.sh "$TAG"` |
| `assets_glob` | `release/*` | files to upload to the release (directories are skipped) |
| `npm_publish`, `npm_package_dirs`, `npm_registry`, `node_version` | false, `release/npm`, `https://npm.pkg.github.com`, `26` | `npm publish` of each whitespace-separated directory built by `assets_command`, in order, with `GITHUB_TOKEN`; versions that already exist are skipped, so reruns are safe |
| `dispatch_repository`, `dispatch_event` | "", `released` | send `repository_dispatch` with `client_payload: {version, tag}` to a repository of the same owner |

Secrets: `RELEASER_APP_PRIVATE_KEY` (required), `RELEASER_APP_ID` (or the
`RELEASER_APP_ID` variable). Callers pass them with `secrets: inherit`.

npm packages go to GitHub Packages (`npm_registry`). Only the publish job gets
`packages: write`, and the caller job must grant it (the `common/release`
template does when `npm_publish` is set; otherwise it grants `packages: read`
for the setup action). Each package needs `publishConfig.registry` set to the
registry and a `repository` field pointing at the publishing repository, which
links the package to it. No npm account or token is involved.

### Installing from GitHub Packages

The `setup` action exports `NPM_GITHUB_TOKEN=${{ github.token }}` to
`bun install`, so a consumer maps its scope in `bunfig.toml`:

```toml
[install.scopes]
roastbook = { url = "https://npm.pkg.github.com/", token = "$NPM_GITHUB_TOKEN" }
```

Tools that read `.npmrc` instead:

```ini
@roastbook:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${NPM_GITHUB_TOKEN}
```

GitHub Packages needs a token even for public packages. Every job that runs the
`setup` action therefore has `packages: read`, and the Open Coffee caller
templates grant it. A public package can be installed by workflows in any
repository; a private or internal one must list the consuming repository under
package settings → **Manage Actions access**. Locally, use
`export NPM_GITHUB_TOKEN="$(gh auth token)"` (the token needs `read:packages`:
`gh auth refresh -s read:packages`).

## Composite actions

- `.github/actions/setup`: Bun (`oven-sh/setup-bun`) from `.bun-version`, a cache
  of `~/.bun/install/cache` keyed by `bun.lock`, and `bun install --frozen-lockfile`
  with `NPM_GITHUB_TOKEN` set for GitHub Packages. Inputs: `install` (true),
  `working-directory` (`.`), `bun-version-file` (`.bun-version`; `package.json`
  reads `packageManager: "bun@x.y.z"`).
- `.github/actions/roast-report`: renders `.roast/report.json` (records and files
  validated, versions, build size, URL, warnings) into `$GITHUB_STEP_SUMMARY`.
  A missing file is reported, not failed. Input: `path`.

Reusable workflows load these actions from `@main`, so their inputs must stay
backward compatible.

## Templates

| Template | Caller file | Params |
|---|---|---|
| `open-coffee/cupping` | `cupping.yml` (`Roastbook · ☕ Cupping (validate)`) | `kind`: `schema` or `data` |
| `open-coffee/roast` | `roast.yml` (`Roastbook · 🔥 Roast (build)`, pull requests) | none |
| `open-coffee/resting` | `resting.yml` (`Roastbook · ⏳ Resting (link and smoke checks)`, weekly) | `kind`, `site_url`, `smoke_paths` (list), `cron` |
| `open-coffee/serve` | `serve.yml` (`Roastbook · 🫖 Serve (deploy)`, main and release tags) | `kind`, `release_tags` |
| `open-coffee/sourcing` | `sourcing.yml` (`Roastbook · 🌱 Sourcing (data agent)`) | `cron` |
| `open-coffee/bump-schema` | `bump-schema.yml` (opens "chore(schema): bump to vX" on `schema-released`) | `version_file` |
| `common/release` | `release.yml` (`Roastbook · 🫘 Release`) | `ci_workflow`, `version_scheme`, `node_setup`, `assets_command`, `assets_glob`, `npm_publish`, `npm_package_dirs`, `npm_registry`, `dispatch_repository`, `dispatch_event`, `name` |

`fixtures/` holds one caller per supported parameter set. The callers in
open-coffee-schema and open-coffee-data are exactly the rendered fixtures
`schema-*.yml` and `data-*.yml`.

Presets that Orcastrate does not sync (it only manages `.github/workflows/`):

- Renovate: every repository extends the shared base config from
  [michidk/workflows](https://github.com/michidk/workflows/blob/main/templates/presets/renovate.json)
  with `"extends": ["github>michidk/workflows//templates/presets/renovate"]` and adds only
  repository-specific rules (for example weekly `Roastbook/workflows` bumps).
- `templates/presets/cliff.toml`: git-cliff configuration for `release.yml`.
  Copy it to `cliff.toml` in the repository root; it accepts both `vX.Y.Z` and
  `YYYY.MM.DD.N` tags.

### Pinned commit of this repository

New callers pin `Roastbook/workflows` to the commit defined once in
`templates/_workflows-ref.yml`. Orcastrate leaves the SHA in existing callers alone,
and Renovate bumps it weekly in each managed repository. Update the template value
when new callers should start from a newer commit.

## How updates reach repositories

1. Merge a template change into `main`.
2. `sync.yml` runs Orcastrate on push, weekly, or manually. It finds every
   repository in the Roastbook org with the topic `managed-workflows`.
3. Orcastrate opens one pull request per drifted caller workflow.

## Onboard a repository

This works for any repository, including michidk/* repositories that move into
the Roastbook org.

1. Add the topic `managed-workflows` to the repository, or add an entry to
   `orchestrator.toml`:

   ```toml
   [[repos]]
   name = "Roastbook/example"
   ```

2. Install the GitHub Apps listed below on the repository.
3. Add each caller under `.github/workflows/` with only the frontmatter, then run
   `orcastrate render .github/workflows/<file>.yml` and commit its output (or wait
   for the sync pull request). For releases:

   ```yaml
   # @orcastrate
   # template: common/release
   # params:
   #   ci_workflow: ci.yml
   # @end-orcastrate
   ```

4. Copy `templates/presets/cliff.toml` to `cliff.toml` when the repository releases.
5. Add `.github/renovate.json5` extending `github>michidk/workflows//templates/presets/renovate`.
6. For Pages sites, add the repository to `scripts/repo-metadata.sh` and run it.

## GitHub Apps, variables and secrets

Create these in the Roastbook org (org-level variables and secrets, shared with the
listed repositories):

- [ ] **Orcastrate App** (Contents, Pull requests, Workflows, Issues: read and write),
      installed on this repository and every managed repository.
      `ORCASTRATE_APP_ID` (variable) and `ORCASTRATE_PRIVATE_KEY` (secret) for `workflows`.
- [ ] **Releaser App** (Contents: read and write, Pull requests: read and write),
      installed on open-coffee-schema and open-coffee-data. `RELEASER_APP_ID`
      (variable or secret) and `RELEASER_APP_PRIVATE_KEY` (secret) for both.
      It tags releases, sends `schema-released`, and opens the schema bump pull request.
- [ ] **Sourcing App** (Contents and Pull requests: read and write), installed on
      open-coffee-data; its bot login must be `roastbook-sourcing[bot]`.
      `SOURCING_APP_ID` (variable) and `SOURCING_APP_PRIVATE_KEY` (secret).
- [ ] open-coffee-data: `LLM_API_KEY` (secret); `LLM_BASE_URL`, `LLM_MODEL`,
      `SOURCING_BUDGET_USD` (variables).
- [ ] After the first open-coffee-schema release: make `@roastbook/open-coffee-schema`
      and `@roastbook/open-coffee-ui` public (package settings → Change visibility),
      or add `open-coffee-data` under **Manage Actions access** (role Read).
- [ ] Org Actions policy allows `Roastbook/workflows` and the pinned third-party actions.

## Repository settings

`scripts/repo-metadata.sh [--dry-run] [repo…]` applies descriptions, homepages,
topics, Discussions on, wiki and projects off, squash merge only, branch deletion
after merge, private vulnerability reporting, and Pages (GitHub Actions source,
custom domain, HTTPS, `github-pages` environment accepting `main` and release tags).
It is idempotent; run it again after DNS resolves so HTTPS can be enforced.

## Development

See [AGENTS.md](AGENTS.md) for the checks that CI runs in `validate.yml`.

## License

[MIT](LICENSE)
