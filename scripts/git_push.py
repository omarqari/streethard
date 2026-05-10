#!/usr/bin/env python3
"""
StreetHard — Git Push via GitHub API

Bypasses local git CLI entirely to avoid sandbox lock-file issues.
Reads changed files, creates blobs, builds a tree, commits, and
fast-forwards main — all via the GitHub REST API.

Usage:
    python3 scripts/git_push.py "commit message" [file1] [file2] ...

If no files are listed, stages everything `git status --porcelain` reports
as modified or untracked (relative to the repo root).

Requires GITHUB_TOKEN in .env (fine-grained PAT with Contents read/write).
"""

import os
import sys
import json
import base64
import subprocess
import urllib.request
import urllib.error

REPO = "omarqari/streethard"
API = f"https://api.github.com/repos/{REPO}"


def load_token():
    """Read GITHUB_TOKEN from .env in the repo root."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path) as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("GITHUB_TOKEN not found in .env")


def api(method, path, body=None, token=None):
    """Make a GitHub API request."""
    url = f"{API}/{path}" if not path.startswith("http") else path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        raise RuntimeError(f"GitHub API {method} {path} → {e.code}: {err_body}")


def get_changed_files(repo_root):
    """Return list of changed/untracked files via git status."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root, capture_output=True, text=True
    )
    files = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # Status is first 2 chars, then space, then path
        path = line[3:].strip()
        # Skip deleted files for now (would need tree entry removal)
        status = line[:2].strip()
        if status == "D":
            continue
        files.append(path)
    return files


def current_branch(repo_root):
    """Detect the current git branch (read-only — safe in sandbox)."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root, capture_output=True, text=True
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch or branch == "HEAD":
        return "main"
    return branch


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Push files to GitHub via REST API")
    parser.add_argument("message", help="Commit message")
    parser.add_argument("files", nargs="*", help="Files to push (default: all changed)")
    parser.add_argument("--branch", help="Target branch (default: current branch)")
    args = parser.parse_args()

    message = args.message
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    token = load_token()
    branch = args.branch or current_branch(repo_root)
    print(f"Target branch: {branch}")

    # Determine files to push
    if args.files:
        files = args.files
    else:
        files = get_changed_files(repo_root)
        if not files:
            print("No changed files detected.")
            sys.exit(0)

    print(f"Pushing {len(files)} file(s): {', '.join(files)}")

    # 1. Get current branch SHA and tree
    ref = api("GET", f"git/ref/heads/{branch}", token=token)
    main_sha = ref["object"]["sha"]
    commit = api("GET", f"git/commits/{main_sha}", token=token)
    base_tree = commit["tree"]["sha"]

    # 2. Create blobs for each file
    tree_entries = []
    for fpath in files:
        full = os.path.join(repo_root, fpath)
        if not os.path.exists(full):
            print(f"  SKIP (not found): {fpath}")
            continue
        with open(full, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
        blob = api("POST", "git/blobs", {
            "content": content_b64,
            "encoding": "base64"
        }, token=token)
        tree_entries.append({
            "path": fpath,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"]
        })
        print(f"  blob: {fpath} → {blob['sha'][:10]}")

    if not tree_entries:
        print("Nothing to push.")
        sys.exit(0)

    # 3. Create new tree
    new_tree = api("POST", "git/trees", {
        "base_tree": base_tree,
        "tree": tree_entries
    }, token=token)
    print(f"  tree: {new_tree['sha'][:10]}")

    # 4. Create commit
    new_commit = api("POST", "git/commits", {
        "message": message,
        "tree": new_tree["sha"],
        "parents": [main_sha]
    }, token=token)
    print(f"  commit: {new_commit['sha'][:10]}")

    # 5. Fast-forward branch
    api("PATCH", f"git/refs/heads/{branch}", {
        "sha": new_commit["sha"]
    }, token=token)
    print(f"✓ Pushed to {branch}: {new_commit['sha'][:10]}")


if __name__ == "__main__":
    main()
