import os
import sys
import tempfile

# Add parent directory of scripts to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from update_changelog import format_changelog, parse_commit, update_changelog_file


def test_parse_commit():
    c_type, scope, msg = parse_commit("feat(sdk): add support for model pricing")
    assert c_type == "feat"
    assert scope == "sdk"
    assert msg == "add support for model pricing"

    c_type, scope, msg = parse_commit("fix: resolve null reference in session handler")
    assert c_type == "fix"
    assert scope is None
    assert msg == "resolve null reference in session handler"

    c_type, scope, msg = parse_commit(
        "random commit message without conventional format"
    )
    assert c_type is None
    assert scope is None
    assert msg == "random commit message without conventional format"


def test_format_changelog():
    commits = [
        {"subject": "feat(cli): implement launcher for local and Docker services"},
        {"subject": "fix(server): resolve next.config.js stray syntax error"},
        {"subject": "chore: update CHANGELOG.md"},  # Should be filtered out
        {
            "subject": "Merge pull request #90 from PxA-Labs/feat/cli-launcher"
        },  # Should be filtered out
        {
            "subject": "feat: add support for changelog generator"
        },  # Should NOT be filtered out just because it contains 'changelog'
    ]

    formatted = format_changelog(commits)

    assert "### Added" in formatted
    assert "### Fixed" in formatted
    assert "**cli**: Implement launcher for local and Docker services" in formatted
    assert "**server**: Resolve next.config.js stray syntax error" in formatted
    assert "Add support for changelog generator" in formatted
    assert "chore: update CHANGELOG.md" not in formatted
    assert "Merge pull request" not in formatted


def test_update_changelog_file_initial_and_update():
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "CHANGELOG.md")

        # Initial write
        initial_content = "### Added\n- **cli**: Implement launcher"
        res1 = update_changelog_file(initial_content, filepath=filepath)
        assert res1 is True

        with open(filepath, "r", encoding="utf-8") as f:
            content1 = f.read()

        assert "## [Unreleased]" in content1
        assert "Implement launcher" in content1

        # Second write (update section, must NOT duplicate header)
        updated_content = (
            "### Added\n- **cli**: Implement launcher\n- **server**: Fix memory leak"
        )
        res2 = update_changelog_file(updated_content, filepath=filepath)
        assert res2 is True

        with open(filepath, "r", encoding="utf-8") as f:
            content2 = f.read()

        # Verify only one [Unreleased] header exists
        assert content2.count("## [Unreleased]") == 1
        assert "Fix memory leak" in content2

        # Third write with identical content should return False
        res3 = update_changelog_file(updated_content, filepath=filepath)
        assert res3 is False
