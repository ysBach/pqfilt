# Release pqfilt

**Publishing a GitHub release automatically runs validation, then uploads to PyPI
only if every check passes. A tag push does not publish.**

## Each release: copy one step at a time

Open a terminal in the repository root. Use the same Bash or zsh session for all
steps so `release_version` stays available. These commands assume `uv` and `gh`
are installed, `gh` is logged in, and your intended code and workflow changes
are committed on `main` or merged into it.

1. **Set the new version once.** Replace `1.2.3` with the version you are releasing.

   ```bash
   release_version=1.2.3
   git switch main &&
   uv version "$release_version" --no-sync
   ```

   This updates `pyproject.toml` and `uv.lock` without syncing your environment.

2. **Date the changelog entry.** In `docs/changelog.rst`, add a heading for the
   version from step 1 and the actual release date, or rename `Unreleased`.
   Keep this release's bullets underneath. Make the underline at least as long
   as the heading. Example:

   ```rst
   v1.2.3 (2000-12-31)
   ------------------
   ```

3. **Commit and push the release files.** The tag must include these changes.

   ```bash
   git add files &&
   git commit -m "prepare release $release_version" &&
   git push origin main
   ```

4. **Wait for CI to pass.** Open [GitHub Actions](https://github.com/ysBach/pqfilt/actions)
   and check the CI run for the commit you just pushed. Tag that same commit
   in the next step.

5. **Publish the release.** This block starts automatic validation and PyPI publishing.

   ```bash
   git tag -a "v$release_version" -m "Release $release_version" &&
   git push origin "v$release_version" &&
   gh release create "v$release_version" --verify-tag \
     --title "v$release_version" --generate-notes
   ```

   Check **Publish to PyPI** in GitHub Actions, then confirm the version on
   [PyPI](https://pypi.org/project/pqfilt/). If a command fails, stop and fix it
   before continuing; `&&` skips the remaining commands in that block.

No manual workflow run is required. For an optional check before tagging, use
GitHub **Actions → Publish to PyPI → Run workflow**. Manual runs **never publish**,
even on tags.

## What runs

CI and release validation use the same artifact workflow:

* Check package and lockfile versions; release runs also check tag and dated notes.
* Build one universal wheel and one sdist with Hatchling.
* Test the installed wheel on Python 3.9–3.13 and the sdist on Python 3.13.
* Publish the tested artifacts only after every validation job passes.

The source archive includes package code, tests, public docs, and release metadata.
Local planning files and workflow files are excluded.

## Publisher settings

Keep the PyPI trusted publisher configured for repository `ysBach/pqfilt`,
workflow `publish.yml`, and GitHub environment `pypi`.
Only the publishing job receives `id-token: write`; no API token is needed.

If nothing uploaded, fix the cause and rerun the failed publishing job.
If only some files uploaded, compare their hashes with the saved workflow
artifacts before uploading only the missing files. A blind rerun can fail on
existing files. Published files cannot be replaced; code changes need a new
version and tag.
