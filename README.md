# Roastbook workflows

Shared GitHub Actions for [Roastbook](https://github.com/Roastbook) repositories:
reusable workflows, composite actions, and the [Orcastrate](https://github.com/michidk/orcastrate)
templates that keep a thin caller workflow in every managed repository up to date.

Managed repositories never copy CI logic. Each one has small caller files such as
`.github/workflows/ci.yml` that start with Orcastrate frontmatter and call a
reusable workflow from this repository at a pinned commit:

```yaml
# @orcastrate
# template: open-coffee/ci
# params:
#   kind: data
# @end-orcastrate

name: CI
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
| `dataset-validate.yml` | as above, plus the agent path rule: pull requests opened by `agent_login` may only change `agent_allowed_paths` | `agent_login` (`roastbook-sourcing[bot]`), `agent_allowed_paths` (`datasets/coffee-places/**`), `actionlint` (true), `timeout_minutes` (15) |
| `site-build.yml` | `scripts/build.sh` on a checkout with full history and tags, so the build can read the release version with `git describe`; pull requests upload a `site-preview-pr-<n>` artifact, other events the Pages artifact. A release tag that is no longer the head of the default branch builds the default branch instead, so a late tag deploy cannot roll the site back. The build receives the caller's repository variables `PUBLIC_UMAMI_SCRIPT_URL`, `PUBLIC_UMAMI_WEBSITE_ID`, `PUBLIC_POSTHOG_TOKEN` and `PUBLIC_POSTHOG_HOST` for the optional tracking in `@roastbook/ui` | `dist` (`dist`), `preview_retention_days` (7), `timeout_minutes` (20) |
| `pages-deploy.yml` | `actions/deploy-pages` into environment `github-pages`, concurrency group `pages` | none; output `page_url` |
| `link-check.yml` | lychee via `scripts/link-check.sh` (warn-only on pull requests, `--full` and failing otherwise) and HTTP smoke checks on scheduled and manual runs | `link_check` (true), `full` (false), `smoke_urls` (""), `lychee_version` and its `lychee_sha256`, `timeout_minutes` (30) |
| `release.yml` | the release flow below | see below |
| `agent-run.yml` | `scripts/agent.sh` with a Sourcing App token scoped to the calling repository (only in `GH_TOKEN`; the checkout keeps no credentials), with `.cache/pages` cached between runs | `app_id`, `llm_base_url`, `llm_model`, `budget_usd` (all required), `timeout_minutes` (180); secrets `app_private_key`, `llm_api_key` |

Every job that runs a script ends with the `summary` action, which turns
`.ci/report.json` into a "CI summary" in the job summary.

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
| `cliff_config`, `git_cliff_version`, `git_cliff_sha256` | `cliff.toml`, `v2.14.2`, its checksum | git-cliff configuration, and the release binary with the SHA-256 of `git-cliff-<version>-x86_64-unknown-linux-gnu.tar.gz` (set both together) |
| `node_setup` | false | run the `setup` action (Bun, `bun install`) before the assets command |
| `assets_command` | "" | shell command with `TAG` and `VERSION` set, e.g. `scripts/release-assets.sh "$TAG"` |
| `assets_glob` | `release/*` | files to upload to the release (directories are skipped) |
| `npm_publish`, `npm_package_dirs`, `npm_registry`, `node_version` | false, `release/npm`, `https://npm.pkg.github.com`, `26` | `npm publish` of each whitespace-separated directory built by `assets_command`, in order, with Trusted Publishing on npmjs.org or `GITHUB_TOKEN` on GitHub Packages; versions that already exist are skipped, so reruns are safe |
| `dispatch_repository`, `dispatch_event` | "", `released` | send `repository_dispatch` with `client_payload: {version, tag}` to a repository of the same owner |

Secrets, both optional: `RELEASER_APP_PRIVATE_KEY` and `RELEASER_APP_ID` (or the
`RELEASER_APP_ID` variable). The `common/release` template passes exactly these two
secrets, not `secrets: inherit`. Without the private key the release falls back to the
job token, which still tags and publishes the release but loses:

- workflows triggered by the tag or release, because GitHub does not start workflows for
  events created with `GITHUB_TOKEN` (for example the Pages deploy on release tags);
- the `repository_dispatch` to `dispatch_repository`, which is skipped with a warning
  (the job token cannot write to another repository).

npm packages go to the registry in `npm_registry`:

- **npmjs.org** (`https://registry.npmjs.org`): Trusted Publishing. The job gets an
  OIDC token (`id-token: write`) and publishes with provenance and public access; no
  npm token is stored. One-time setup per package on npmjs.com: the package belongs
  to the `roastbook` npm organisation, and its Trusted Publisher is this caller
  (repository `Roastbook/<repo>`, workflow `release.yml`). npm only lets you add a
  Trusted Publisher to an existing package, so the very first version is published
  by hand (`npm publish --access public` from `release/npm` of a release).
- **GitHub Packages** (`https://npm.pkg.github.com`): the job token
  (`packages: write`). Installing needs a token even for public packages.

The caller job must grant the same permissions; the `common/release` template grants
`id-token: write` and `packages: write` when `npm_publish` is set (otherwise
`packages: read` for the setup action). Each package needs `publishConfig.registry`
set to the registry and a `repository` field pointing at the publishing repository.

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
- `.github/actions/summary`: renders `.ci/report.json` (records and files
  validated, versions, build size, URL, warnings) into `$GITHUB_STEP_SUMMARY`.
  A missing file is reported, not failed. Input: `path`.

### Pinned composite actions

Reusable workflows load these actions at a full commit SHA, so a caller's pin of
`Roastbook/workflows` also fixes the actions it runs. A commit cannot reference its own
SHA, so the pin is the last commit that changed `.github/actions`, set by
`scripts/pin-actions.sh`. To change an action:

1. Merge the change to `.github/actions/` (the workflows still use the previous pin).
2. On an up-to-date `main`, run `bash scripts/pin-actions.sh` and merge the result as
   `chore: pin composite actions to <sha>`.
3. Only then bump `templates/_workflows-ref.yml` and the callers to a commit that
   contains step 2.

`validate.yml` runs `scripts/pin-actions.sh --check`: it fails when the references
differ or the pin is not an ancestor of `HEAD`, and warns while `.github/actions` has
changes that are not pinned yet. Keep action inputs backward compatible, because
callers on older pins still run older actions.

## Templates

| Template | Caller file | Params |
|---|---|---|
| `open-coffee/ci` | `ci.yml` (`CI`) | `kind`: `schema` or `data` |
| `open-coffee/build` | `build.yml` (`Build`, pull requests) | none |
| `open-coffee/link-check` | `link-check.yml` (`Link check`, weekly) | `kind`, `site_url`, `smoke_paths` (list), `cron` |
| `open-coffee/deploy` | `deploy.yml` (`Deploy`, main and release tags) | `kind`, `release_tags` |
| `open-coffee/data-agent` | `data-agent.yml` (`Data agent`) | `cron` |
| `open-coffee/bump-schema` | `bump-schema.yml` (on `schema-released`, rewrites the `$schema` URLs in `datasets/**/*.json` to the new version and opens "chore(schema): bump to vX" listing the changed files) | none |
| `common/release` | `release.yml` (`Release`); free-form string params are rendered single-quoted, so `#` and `: ` survive | `ci_workflow`, `version_scheme`, `node_setup`, `assets_command`, `assets_glob`, `npm_publish`, `npm_package_dirs`, `npm_registry`, `dispatch_repository`, `dispatch_event`, `name` |

`fixtures/` holds one caller per supported parameter set. The callers in
open-coffee-schema and open-coffee-data are exactly the rendered fixtures
`schema-*.yml` and `data-*.yml`.

Presets that Orcastrate does not sync (it only manages `.github/workflows/`):

- Renovate: every repository extends the shared base config from
  [michidk/workflows](https://github.com/michidk/workflows/blob/main/templates/presets/renovate.json)
  with `"extends": ["github>michidk/workflows//templates/presets/renovate"]` and adds only
  repository-specific rules (for example weekly `Roastbook/workflows` bumps).
  Libraries such as `@roastbook/ui` extend
  `github>michidk/workflows//templates/presets/renovate-library` instead: it keeps
  compatible version ranges for consumers rather than pinning exact versions.
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
5. Add `.github/renovate.json5` extending `github>michidk/workflows//templates/presets/renovate`
   (`renovate-library` for libraries).
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
      open-coffee-data only; its GitHub App login must be `roastbook-sourcing[bot]`.
      `SOURCING_APP_ID` (variable) and `SOURCING_APP_PRIVATE_KEY` (secret).
      Add the rulesets in [Data agent rulesets](#data-agent-rulesets).
- [ ] open-coffee-data: `LLM_API_KEY` (secret); `LLM_BASE_URL`, `LLM_MODEL`,
      `SOURCING_BUDGET_USD` (variables).
- [ ] After the first open-coffee-schema release: make `@roastbook/open-coffee-schema`
      and `@roastbook/open-coffee-ui` public (package settings → Change visibility),
      or add `open-coffee-data` under **Manage Actions access** (role Read).
- [ ] Org Actions policy allows `Roastbook/workflows` and the pinned third-party actions.

### Data agent rulesets

The data agent reads untrusted web pages while holding a token with Contents and Pull
requests write. `agent-run.yml` scopes that token to the calling repository and keeps it
out of the Git configuration, but only rulesets stop the App from writing elsewhere. The
agent creates branches named `data-agent/<city>-<date>-<id>` and opens pull requests into
`main`. Recommended rulesets for open-coffee-data (Settings → Rules → Rulesets → New
branch ruleset; not applied by `scripts/repo-metadata.sh`):

1. **Sourcing App branches**
   - Enforcement status: Active
   - Bypass list (Always allow): Repository admin role, Maintain role, Write role, the
     Orcastrate App, the Releaser App and the Renovate App. Do not add the Sourcing App.
   - Target branches: Include all branches; Exclude by pattern `data-agent/**`
   - Rules: Restrict creations, Restrict updates, Restrict deletions

   The Sourcing App can then create and update only `data-agent/**` branches.
   GitHub Apps are not matched by the role entries; confirm after setup that an
   API branch creation outside `data-agent/**` with a Sourcing App token is rejected.
2. **Protect main**
   - Enforcement status: Active
   - Bypass list: empty
   - Target branches: Include default branch
   - Rules: Restrict deletions; Block force pushes; Require a pull request before
     merging (1 required approval, dismiss stale approvals when new commits are pushed,
     require approval of the most recent reviewable push, require conversation
     resolution, allowed merge method Squash); Require status checks to pass, with
     "Require branches to be up to date before merging" and the checks
     `Validate / Validate dataset`, `Validate / Agent path rule` and
     `Validate / Lint workflows`.

   `Agent path rule` only runs on the agent's pull requests and counts as passed when
   skipped; on agent pull requests it rejects changes outside `agent_allowed_paths`.

## Repository settings

`scripts/repo-metadata.sh [--dry-run] [repo…]` applies descriptions, homepages,
topics, Discussions on, wiki and projects off, squash merge only, branch deletion
after merge, private vulnerability reporting, and Pages (GitHub Actions source,
custom domain, HTTPS, `github-pages` environment accepting `main` and release tags).
It is idempotent; run it again after DNS resolves so HTTPS can be enforced.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for the rules and the checks that CI runs in `validate.yml`.

## License

[MIT](LICENSE)
