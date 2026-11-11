#!/usr/bin/env python3
"""Sync the current git-tracked tree to GitHub through the REST API.

Why this exists: some networks allow api.github.com but block the git smart-HTTP
endpoint. `ship.sh` prefers this path when GITHUB_TOKEN is set, and falls back to
`git push` otherwise.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_requests():
    try:
        from curl_cffi import requests as curl_requests
        return curl_requests.Session(impersonate="chrome", timeout=90), True
    except Exception:
        import urllib.request
        return None, False


def repo_slug():
    pkg = json.loads((ROOT / "package.json").read_text())
    url = pkg.get("repository", {}).get("url", "")
    url = url.removeprefix("git+").removesuffix(".git")
    if "github.com/" not in url:
        raise SystemExit("package.json repository must point at github.com")
    owner, repo = url.split("github.com/", 1)[1].split("/", 1)
    return owner, repo, pkg["version"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("message")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN/GH_TOKEN is not set")

    owner, repo, version = repo_slug()
    api = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    session, use_curl = load_requests()

    def request(method, url, data=None):
        last = None
        for attempt in range(5):
            try:
                if use_curl:
                    response = session.request(method, url, headers=headers, json=data)
                    status = response.status_code
                    body = response.text
                else:
                    import urllib.request
                    req = urllib.request.Request(
                        url,
                        data=None if data is None else json.dumps(data).encode(),
                        headers=headers,
                        method=method,
                    )
                    with urllib.request.urlopen(req, timeout=90) as resp:
                        status = resp.status
                        body = resp.read().decode()
                if status >= 400:
                    raise RuntimeError(f"{method} {url} -> {status}: {body[:600]}")
                return json.loads(body)
            except Exception as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise last

    ref = request("GET", f"{api}/git/ref/heads/main")
    parent = ref["object"]["sha"]

    files = [
        item for item in subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT
        ).decode().split("\0") if item
    ]
    entries = []
    for i, relative in enumerate(files, 1):
        path = ROOT / relative
        if path.is_symlink():
            content = os.readlink(path).encode()
            mode = "120000"
        else:
            content = path.read_bytes()
            mode = "100644"
        blob = request(
            "POST",
            f"{api}/git/blobs",
            {"content": base64.b64encode(content).decode(), "encoding": "base64"},
        )
        entries.append({"path": relative, "mode": mode, "type": "blob", "sha": blob["sha"]})
        if i % 10 == 0:
            print(f"  uploaded {i}/{len(files)}", file=sys.stderr)

    tree = request("POST", f"{api}/git/trees", {"tree": entries})
    commit = request(
        "POST",
        f"{api}/git/commits",
        {"message": args.message, "tree": tree["sha"], "parents": [parent]},
    )
    request("PATCH", f"{api}/git/refs/heads/main", {"sha": commit["sha"], "force": True})
    print(f"✓ synced {len(files)} files to {owner}/{repo}@{commit['sha'][:8]}")

    if args.tag:
        tag = args.tag if args.tag.startswith("v") else f"v{args.tag}"
        try:
            request(
                "POST",
                f"{api}/git/refs",
                {"ref": f"refs/tags/{tag}", "sha": commit["sha"]},
            )
            print(f"✓ tag {tag} created")
        except Exception as exc:
            if "already exists" in str(exc):
                print(f"= tag {tag} already exists")
            else:
                raise

    print(f"  {commit['html_url']}")


if __name__ == "__main__":
    main()
