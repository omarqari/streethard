#!/usr/bin/env python3
"""
StreetHard — Silent-Revert Audit

Walks every commit on `main`, extracts each commit's distinctive added lines
per file, and checks whether those lines still survive in the current state of
that file on `main`. Flags any commit/file pair with low survival as a candidate
for silent overwrite (the "rebase-forward antipattern" — see Session 31 in
CHANGELOG.md for the cautionary tale).

Why this exists
---------------
On 2026-05-13 we discovered that a Session 30 "restore mobile" commit had
forward-ported an *older snapshot* of `index.html` over later refinement
commits, silently overwriting the green/red bucket-aware swipe behavior added
in commits 9a28476 and a272ec6. The commit SHAs remained reachable from main's
log, so the work *looked* present until you actually checked the file content.

This script automates the check: for every commit, sample its longest added
lines and substring-search current main. Anything missing is suspect.

Usage
-----
    python3 scripts/audit_silent_reverts.py
    python3 scripts/audit_silent_reverts.py --threshold 0.3   # only show <30% survival
    python3 scripts/audit_silent_reverts.py --since 2026-05-01

Caveats
-------
False positives are common for docs/markdown files (CLAUDE.md, TASKS.md,
*.md) because text gets continuously rewritten. Flagged docs commits are
usually fine — verify by reading the section, not the script. For functional
code (.py, .html, .sql, .js), low survival is more meaningful and worth
investigating.

Requires GITHUB_TOKEN in .env (fine-grained PAT with Contents read).
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

REPO = "omarqari/streethard"
API = f"https://api.github.com/repos/{REPO}"

# Files we care about — skip generated data and lockfiles
CODE_FILE_RE = re.compile(r"\.(py|html|css|js|jsx|sql|md|toml|yml|yaml|sh|json)$")
SKIP_FILES = {
    "data/db.json",
    "data/latest.json",
    "data/pipeline_health.json",
    "package-lock.json",
    "poetry.lock",
}


def is_code(path):
    """True if `path` is a source-of-truth file worth auditing."""
    if path in SKIP_FILES:
        return False
    if path.startswith("data/") and path.endswith(".json"):
        return False  # dated archives / generated
    return bool(CODE_FILE_RE.search(path))


def load_token():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path) as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("GITHUB_TOKEN not found in .env")


def gh(path, accept="application/vnd.github+json", token=None):
    """GitHub API GET with retry on transient 5xx."""
    url = f"{API}/{path}" if not path.startswith("http") else path
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", accept)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if "json" in accept:
                    return json.load(r)
                return r.read().decode()
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def fetch_commits(token, since=None):
    """Walk all commits on main (paginated)."""
    commits = []
    page = 1
    while True:
        path = f"commits?sha=main&per_page=100&page={page}"
        if since:
            path += f"&since={since}T00:00:00Z"
        data = gh(path, token=token)
        if not data:
            break
        commits.extend(data)
        if len(data) < 100:
            break
        page += 1
    return commits


def extract_added(diff_text, target_path):
    """Return distinctive added lines from `diff_text` for `target_path`."""
    out = []
    in_path = False
    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            in_path = f" b/{target_path}" in line
            continue
        if not in_path:
            continue
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            stripped = line[1:].strip()
            # Threshold: >= 30 chars and at least one alphanumeric run
            if len(stripped) < 30:
                continue
            if not re.search(r"[A-Za-z0-9]{6}", stripped):
                continue
            out.append(stripped)
    return out


def parse_files_from_diff(diff_text):
    """Return dict of {path: [added_lines]} for code files in the diff."""
    per_file = {}
    in_path = None
    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            in_path = parts[1].strip() if len(parts) == 2 else None
            if in_path and not is_code(in_path):
                in_path = None
            if in_path:
                per_file.setdefault(in_path, [])
            continue
        if in_path is None:
            continue
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            s = line[1:].strip()
            if len(s) >= 30 and re.search(r"[A-Za-z0-9]{6}", s):
                per_file[in_path].append(s)
    return per_file


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Survival rate threshold (0.0–1.0); only commits below this are flagged. Default 0.5.",
    )
    parser.add_argument(
        "--since",
        help="ISO date (YYYY-MM-DD) — only audit commits on or after this date.",
    )
    parser.add_argument(
        "--include-docs",
        action="store_true",
        help="Include .md docs files in the report (they're noisy — off by default in summary).",
    )
    args = parser.parse_args()

    token = load_token()
    print(f"Fetching commit list from {REPO}...")
    commits = fetch_commits(token, since=args.since)
    print(f"Total commits to audit: {len(commits)}")
    commits.reverse()  # oldest-first

    # Cache current-main file contents
    file_cache = {}

    def current(path):
        if path in file_cache:
            return file_cache[path]
        try:
            d = gh(f"contents/{path}?ref=main", token=token)
            content = base64.b64decode(d["content"]).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            content = None if e.code == 404 else None
        file_cache[path] = content
        return content

    print("\nProcessing commits (1 GET per commit + 1 GET per unique file)...\n")
    results = []
    for c in commits:
        sha = c["sha"]
        msg = c["commit"]["message"].splitlines()[0]
        date = c["commit"]["author"]["date"][:10]
        if len(c.get("parents", [])) > 1:
            continue  # skip merges (their diff double-counts)
        if msg.startswith("chore: refresh listings"):
            continue  # cron noise
        try:
            diff = gh(f"commits/{sha}", accept="application/vnd.github.v3.diff", token=token)
        except Exception as e:
            print(f"  ! {sha[:8]} diff fetch failed: {e}")
            continue

        per_file = parse_files_from_diff(diff)
        for path, added in per_file.items():
            if not added:
                continue
            cur = current(path)
            if cur is None:
                results.append((date, sha[:8], msg[:60], path, len(added), 0, len(added), 0.0, "FILE-DELETED"))
                continue
            distinctive = sorted(set(added), key=len, reverse=True)[:25]
            present = sum(1 for ln in distinctive if ln in cur)
            survival = present / len(distinctive) if distinctive else 1.0
            results.append((date, sha[:8], msg[:60], path, len(distinctive), present, len(distinctive) - present, survival, ""))

    # Filter and sort
    flagged = [r for r in results if r[7] < args.threshold]
    if not args.include_docs:
        flagged = [r for r in flagged if not r[3].endswith(".md")]
    flagged.sort(key=lambda r: r[7])

    print("=" * 100)
    print(f'{"DATE":<12} {"SHA":<10} {"FILE":<32} {"SAMP":>5} {"OK":>5} {"GONE":>5} {"SURV":>6}  MESSAGE')
    print("-" * 100)
    for date, sha, msg, path, samp, ok, gone, surv, note in flagged:
        marker = "⚠⚠" if surv < 0.2 else "⚠ "
        print(f"{marker} {date:<10} {sha:<10} {path:<32} {samp:>5} {ok:>5} {gone:>5} {int(surv * 100):>4}%  {msg}")

    print("=" * 100)
    print(f"Audited {len(results)} commit/file pairs across {len(file_cache)} files.")
    print(f"Flagged {len(flagged)} below survival threshold {args.threshold:.0%}{' (excluding docs)' if not args.include_docs else ''}.")
    if flagged:
        print(f"\nNext step: for each flagged item, run `git show <SHA> -- <FILE>` to read the diff,")
        print(f"then read the current file to determine if the change was intentionally refactored")
        print(f"or silently overwritten. Functional code (.py/.html/.sql) findings are higher signal")
        print(f"than docs (.md). See Session 31 in CHANGELOG.md for an example investigation.")


if __name__ == "__main__":
    sys.exit(main())
