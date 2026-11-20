# Releasing the SDK

The Python SDK in `packages/sdk` is published to PyPI as **`agentscope-trace`** (the names `agentscope` and `agentscope-sdk` belong to unrelated projects). Releases are automated by [`.github/workflows/release.yml`](.github/workflows/release.yml) and triggered by pushing a version tag.

## One-time setup (maintainers)

1. **Reserve the name.** Create the project on PyPI and TestPyPI by configuring a *pending* Trusted Publisher. No upload or API token is needed:
   - PyPI → *Your account → Publishing → Add a new pending publisher*
     - PyPI project name: `agentscope-trace`
     - Owner: `PxA-Labs`, repository: `AgentsScope`
     - Workflow: `release.yml`, environment: `pypi`
   - Repeat on TestPyPI (`https://test.pypi.org`) with environment `testpypi`.
2. **Create the GitHub environments** `testpypi` and `pypi` (*Settings → Environments*) **before the first tag is pushed**. If a tag arrives first, GitHub creates them automatically with no protection, and PyPI would publish without approval. On both, set *Deployment branches and tags* to **selected tags** matching `v*`. Add **required reviewers** to `pypi` so every production publish needs a human approval.
3. **Restrict who can create release tags.** Add a tag ruleset (*Settings → Rules → Rulesets → New tag ruleset*) targeting `v*` that restricts creation, update and deletion to maintainers.
4. No secrets are needed. The workflow authenticates with OIDC (`id-token: write`).

## Cutting a release

1. Open a PR that:
   - bumps `__version__` in [`packages/sdk/agentscope_trace/_version.py`](packages/sdk/agentscope_trace/_version.py) (SemVer: patch for fixes, minor for features, major for breaking changes; `X.Y.ZrcN` for release candidates)
   - moves the relevant `CHANGELOG.md` entries under the new version
2. After it merges, tag the merge commit on `main` and push the tag:
   ```bash
   git checkout main && git pull
   git tag -a v0.2.0 -m "agentscope-trace 0.2.0"
   git push origin v0.2.0
   ```
3. The workflow then:
   1. checks the tagged commit is on `main`, and fails otherwise
   2. checks the tag matches `_version.py` (`.github/scripts/check_release_version.py`) and fails otherwise
   3. builds the sdist and wheel, runs `twine check --strict`, and smoke-tests the wheel in a clean virtualenv (import, version metadata, `agentscope --help`)
   4. publishes to **TestPyPI**, then waits for the `pypi` environment approval and publishes to **PyPI**
   5. attaches build-provenance attestations and creates a **GitHub Release** with the artifacts and generated notes (marked as a pre-release for `aN`, `bN` and `rcN` tags)
4. Verify: `pip install agentscope-trace==0.2.0` in a fresh virtualenv.

If any step fails, nothing further is published. Fix the problem in a PR, delete the tag (`git push --delete origin v0.2.0`), and tag again. The TestPyPI step uses `skip-existing`, so re-tagging the same version still gets through it to the PyPI step. PyPI never accepts the same version twice, so if a broken build was already uploaded to PyPI, bump to the next patch version instead.

## After the first release

- Update the install instructions in `README.md` and `packages/sdk/README.md` to `pip install agentscope-trace` (they currently say to install from source, because nothing is published yet).
- Add a PyPI version badge to the README.

## The `agentscope` compatibility shim

The import package is `agentscope_trace` ([#297](https://github.com/PxA-Labs/AgentsScope/issues/297)). The wheel still ships a one-file `agentscope` package (`packages/sdk/agentscope/__init__.py`) that aliases `agentscope_trace` and emits a `DeprecationWarning`, so existing `import agentscope` code keeps working.

That shim is the only file that still clashes with the unrelated `agentscope` project on PyPI: installing both overwrites `agentscope/__init__.py` (`packages/sdk/tests/test_wheel_install.py` documents this). So:

- The GitHub release notes of the first release that contains the rename must include the migration notes from [CHANGELOG.md](CHANGELOG.md) (`--generate-notes` only lists PR titles; edit the release after it is created).
- Keep the shim for at least one full minor release after that first release, then remove it in a minor release: delete `packages/sdk/agentscope/`, drop `"agentscope"` from `packages` in `packages/sdk/pyproject.toml`, delete `packages/sdk/tests/test_import_shim.py`, invert the clash test in `test_wheel_install.py`, and drop the shim check from the release smoke test.
