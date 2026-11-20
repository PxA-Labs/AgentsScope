# Releasing the SDK

The Python SDK in `packages/sdk` is published to PyPI as **`agentscope-trace`** (the names `agentscope` and `agentscope-sdk` belong to unrelated projects). Releases are automated by [`.github/workflows/release.yml`](.github/workflows/release.yml) and triggered by pushing a version tag.

## One-time setup (maintainers)

1. **Reserve the name.** Create the project on PyPI and TestPyPI by configuring a *pending* Trusted Publisher. No upload or API token is needed:
   - PyPI → *Your account → Publishing → Add a new pending publisher*
     - PyPI project name: `agentscope-trace`
     - Owner: `PxA-Labs`, repository: `AgentsScope`
     - Workflow: `release.yml`, environment: `pypi`
   - Repeat on TestPyPI (`https://test.pypi.org`) with environment `testpypi`.
2. **Create the GitHub environments** `testpypi` and `pypi` (*Settings → Environments*). Add **required reviewers** to `pypi` so every production publish needs a human approval.
3. No secrets are needed. The workflow authenticates with OIDC (`id-token: write`).

## Cutting a release

1. Open a PR that:
   - bumps `__version__` in [`packages/sdk/agentscope/_version.py`](packages/sdk/agentscope/_version.py) (SemVer: patch for fixes, minor for features, major for breaking changes; `X.Y.ZrcN` for release candidates)
   - moves the relevant `CHANGELOG.md` entries under the new version
2. After it merges, tag the merge commit on `main` and push the tag:
   ```bash
   git checkout main && git pull
   git tag -a v0.2.0 -m "agentscope-trace 0.2.0"
   git push origin v0.2.0
   ```
3. The workflow then:
   1. checks the tag matches `_version.py` (`.github/scripts/check_release_version.py`) and fails otherwise
   2. builds the sdist and wheel, runs `twine check --strict`, and smoke-tests the wheel in a clean virtualenv (import, version metadata, `agentscope --help`)
   3. publishes to **TestPyPI**, then waits for the `pypi` environment approval and publishes to **PyPI**
   4. attaches build-provenance attestations and creates a **GitHub Release** with the artifacts and generated notes
4. Verify: `pip install agentscope-trace==0.2.0` in a fresh virtualenv.

If any step fails, nothing further is published. Fix the problem in a PR, delete the tag (`git push --delete origin v0.2.0`), and tag again. The TestPyPI step uses `skip-existing`, so re-tagging the same version still gets through it to the PyPI step. PyPI never accepts the same version twice, so if a broken build was already uploaded to PyPI, bump to the next patch version instead.

## After the first release

- Update the install instructions in `README.md` and `packages/sdk/README.md` to `pip install agentscope-trace` (they currently say to install from source, because nothing is published yet).
- Add a PyPI version badge to the README.

## Known follow-up

The import package is still named `agentscope`, the same top-level module as the unrelated `agentscope` project on PyPI, so the two can't be installed in the same environment. Renaming the import package is tracked in [#297](https://github.com/PxA-Labs/AgentsScope/issues/297) and will ship with a compatibility shim.
