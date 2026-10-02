"""Synchronize branches across the three authorized EHPAD repositories.

No force push, branch deletion, or working-tree modification. Divergent histories
require an explicit reconciliation instead of silently discarding commits.
"""
import argparse
import json
import subprocess

REPOSITORIES = {
    'origin': 'https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD.git',
    'delivery': 'https://github.com/lebretyves/epitech_mba2_ehpadMonitor.git',
    'faucourt': 'https://github.com/Faucourt/epitech_mba2_ehpadMonitor.git',
}


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def remote_heads(remote):
    return {ref.removeprefix('refs/heads/'): sha for sha, ref in
            (line.split() for line in git('ls-remote', '--heads', remote).splitlines())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    for remote, url in REPOSITORIES.items():
        configured = git('remote', 'get-url', remote)
        if configured.rstrip('/').removesuffix('.git') != url.removesuffix('.git'):
            raise SystemExit(f'Unexpected destination for {remote}: refusing to publish')
        subprocess.run(['git', 'fetch', remote], check=True)
    heads = {remote: remote_heads(remote) for remote in REPOSITORIES}
    branches = sorted(set().union(*(set(h) for h in heads.values())))
    desired = {}
    for branch in branches:
        candidates = {h[branch] for h in heads.values() if branch in h}
        descendants = [sha for sha in candidates if all(
            subprocess.run(['git', 'merge-base', '--is-ancestor', older, sha]).returncode == 0
            for older in candidates)]
        if len(descendants) != 1:
            raise SystemExit(f'Divergent branch {branch}: reconcile before synchronization; no force push performed')
        desired[branch] = descendants[0]
    updates = {remote: {name: sha for name, sha in desired.items() if heads[remote].get(name) != sha}
               for remote in REPOSITORIES}
    print(json.dumps({'branches': desired, 'updates': updates}, indent=2))
    if any(updates.values()) and not args.apply:
        raise SystemExit('Differences found. Use --apply to publish the listed fast-forward additions.')
    if args.apply:
        for remote, changes in updates.items():
            if changes:
                subprocess.run(['git', 'push', '--atomic', remote,
                                *(f'{sha}:refs/heads/{name}' for name, sha in changes.items())], check=True)
    actual = {remote: remote_heads(remote) for remote in REPOSITORIES}
    if any(h != desired for h in actual.values()):
        raise SystemExit('Remote heads changed during synchronization. Recheck before reporting completion.')
    print(f'VERIFIED: {len(desired)} identical branch heads on all three repositories')


if __name__ == '__main__':
    main()
