#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

def run_cmd(args):
    result = subprocess.run(args, capture_output=True, text=True, check=True, encoding="utf-8")
    return result.stdout.strip()

def get_last_changelog_commit():
    try:
        # Get the hash of the last commit that touched CHANGELOG.md
        commit = run_cmd(["git", "log", "-1", "--format=%H", "--", "CHANGELOG.md"])
        if commit:
            return commit.splitlines()[0]
    except (subprocess.CalledProcessError, IndexError):
        pass
    
    # Fallback to the first commit of the repository
    try:
        commit = run_cmd(["git", "rev-list", "--max-parents=0", "HEAD"])
        if commit:
            return commit.splitlines()[0]
    except (subprocess.CalledProcessError, IndexError):
        print("Error: Could not retrieve git history.", file=sys.stderr)
        sys.exit(1)

def get_commits_since(commit_hash):
    # Get all commits since commit_hash to HEAD (excluding merge commits)
    # Using %H (hash), %s (subject), %b (body) separated by null bytes
    log_format = "%H%x00%s%x00%b%x1e"
    try:
        stdout = run_cmd(["git", "log", f"{commit_hash}..HEAD", "--no-merges", f"--format={log_format}"])
    except subprocess.CalledProcessError:
        print(f"Error running git log for range {commit_hash}..HEAD", file=sys.stderr)
        return []
    
    if not stdout:
        return []
    
    commits = []
    # Commits are separated by RS (0x1e) and a newline
    for record in stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x00")
        if len(parts) >= 2:
            c_hash = parts[0]
            subject = parts[1]
            body = parts[2] if len(parts) > 2 else ""
            commits.append({"hash": c_hash, "subject": subject, "body": body})
    return commits

def parse_commit(subject):
    # Match conventional commit pattern: type(scope): message
    # e.g., feat(sdk): add support for Claude 3
    pattern = r"^(\w+)(?:\(([^)]+)\))?\s*:\s*(.*)$"
    match = re.match(pattern, subject)
    if match:
        commit_type = match.group(1).lower()
        scope = match.group(2)
        message = match.group(3).strip()
        return commit_type, scope, message
    return None, None, subject

def format_changelog(commits):
    categories = {
        "feat": "Added",
        "fix": "Fixed",
        "docs": "Documentation",
        "perf": "Performance",
        "refactor": "Refactor",
        "test": "Tests",
        "chore": "Maintenance",
        "style": "Style",
        "ci": "CI/CD",
    }
    
    grouped = {name: [] for name in categories.values()}
    other = []
    
    # Filter and categorize
    for commit in commits:
        subj = commit["subject"]
        subj_lower = subj.lower().strip()
        
        # Skip automated changelog commits and merge PR commits to avoid recursion
        if (
            subj_lower.startswith("chore: update changelog")
            or subj_lower == "chore: update changelog.md"
            or "merge pull request" in subj_lower
            or "merge branch" in subj_lower
        ):
            continue
            
        c_type, scope, msg = parse_commit(subj)
        if c_type in categories:
            cat_name = categories[c_type]
            # Capitalize first letter of description message
            if msg:
                msg = msg[0].upper() + msg[1:]
            # Format message with scope if present
            formatted_msg = f"**{scope}**: {msg}" if scope else msg
            grouped[cat_name].append(formatted_msg)
        else:
            # Capitalize first letter
            if subj:
                subj = subj[0].upper() + subj[1:]
            other.append(subj)
            
    # Generate Markdown
    lines = []
    for cat_name, msgs in grouped.items():
        if msgs:
            lines.append(f"### {cat_name}")
            for msg in msgs:
                lines.append(f"- {msg}")
            lines.append("")
            
    if other:
        lines.append("### Miscellaneous")
        for msg in other:
            lines.append(f"- {msg}")
        lines.append("")
        
    return "\n".join(lines).strip()

def update_changelog_file(new_content, filepath="CHANGELOG.md"):
    if not new_content:
        print("No new changes to add to CHANGELOG.md.")
        return False
        
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "# Changelog\n\nAll notable changes to the **AgentScope** project will be documented in this file.\n\n"
        
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"## [Unreleased] - {date_str}"
    section = f"{header}\n\n{new_content}"
    
    lines = content.splitlines()
    
    unreleased_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("## [Unreleased]"):
            unreleased_idx = idx
            break
            
    if unreleased_idx != -1:
        # Find end of existing [Unreleased] section (next '## ' header or end of file)
        end_idx = len(lines)
        for idx in range(unreleased_idx + 1, len(lines)):
            if lines[idx].startswith("## "):
                end_idx = idx
                break
        new_lines = lines[:unreleased_idx] + section.splitlines() + [""] + lines[end_idx:]
    else:
        # Insert before first version header starting with "## "
        first_version_idx = -1
        for idx, line in enumerate(lines):
            if line.startswith("## "):
                first_version_idx = idx
                break
                
        if first_version_idx != -1:
            new_lines = lines[:first_version_idx] + section.splitlines() + [""] + lines[first_version_idx:]
        else:
            new_lines = lines + ["", section]
            
    final_content = "\n".join(new_lines).strip() + "\n"
    
    if os.path.exists(filepath) and final_content == content:
        print("CHANGELOG.md is already up to date.")
        return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(final_content)
        
    print(f"{filepath} updated successfully.")
    return True

def main():
    last_commit = get_last_changelog_commit()
    print(f"Last changelog commit: {last_commit}")
    
    commits = get_commits_since(last_commit)
    print(f"Found {len(commits)} commits since last changelog update.")
    
    if not commits:
        print("No new commits found.")
        sys.exit(0)
        
    new_content = format_changelog(commits)
    if update_changelog_file(new_content):
        sys.exit(0)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()

