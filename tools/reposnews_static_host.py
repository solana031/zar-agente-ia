"""GitHub Pages adapter for an already approved, immutable static artifact.

No credentials, DNS changes, domain association, build or editorial mutations.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from urllib.parse import urlsplit

REPO = 'solana031/solana031.github.io'
PREVIEW = 'https://solana031.github.io'


def cutover_plan(dns_snapshot):
    """Generate a reversible plan only. This module has no DNS write operation."""
    return {
        'canonical': 'https://www.reposnews.com', 'target_hostname': 'solana031.github.io',
        'dns_changed': False, 'approval_required': True,
        'current_dns': dns_snapshot,
        'target_dns': [
            {'name': 'www', 'type': 'CNAME', 'values': ['solana031.github.io'], 'ttl': 3600},
            {'name': '@', 'type': 'A', 'values': ['185.199.108.153', '185.199.109.153', '185.199.110.153', '185.199.111.153'], 'ttl': 3600},
            {'name': '@', 'type': 'AAAA', 'values': ['2606:50c0:8000::153', '2606:50c0:8001::153', '2606:50c0:8002::153', '2606:50c0:8003::153'], 'ttl': 3600},
        ],
        'before_dns': 'After explicit cutover approval only: associate www.reposnews.com in GitHub Pages; export the IONOS zone and compare with this snapshot.',
        'ssl': 'GitHub-managed certificate; wait for issuance and enable Enforce HTTPS. Verify both hostnames before declaring cutover complete.',
        'redirects': 'HTTP to HTTPS; apex to www; retain all ES/EN paths. Canonical remains www.',
        'rollback': 'Restore the saved A/AAAA/CNAME values at IONOS, keep Railway serving www, verify HTTPS and paths. Do not change nameservers, MX or TXT.',
        'static_rollback': 'Revert the failed static-host commit with a new commit; push main and verify Pages. Never force-push.',
        'source': 'https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site',
    }


def artifact_files(root):
    root = Path(root).resolve()
    manifest = json.loads((root/'build-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'STATIC_HOST_READY' or manifest.get('backend_required') is not False:
        raise ValueError('VERIFIED_STATIC_ARTIFACT_REQUIRED')
    files = sorted(p for p in root.rglob('*') if p.is_file())
    for path in files:
        name = path.relative_to(root).as_posix()
        allowed = (name in {'index.html', 'sitemap.xml', 'robots.txt', 'ads.txt', 'build-manifest.json'}
                   or name.startswith(('es/', 'en/')) and name.endswith('/index.html')
                   or name.startswith('media/reposnews/') and path.suffix in {'.png', '.svg', '.jpg', '.webp', '.css', '.js'})
        if path.is_symlink() or root not in path.resolve().parents or not allowed:
            raise ValueError('NONPUBLIC_ARTIFACT_FILE')
    return root, files


def artifact_digest(root):
    root, files = artifact_files(root)
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode()+b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def deploy(root, approved_sha256, workspace, public_base=PREVIEW):
    """Deploy exactly the reviewed build. Separate Git repo; no force pushes.

    Caller must pass the approved artifact fingerprint, not a draft/revision ID.
    Every attempt uses a fresh checkout. Failed pushes leave the live site intact.
    """
    if public_base not in {PREVIEW, 'https://www.reposnews.com'}:
        raise ValueError('PUBLIC_HOST_REQUIRED')
    root, files = artifact_files(root)
    if artifact_digest(root) != approved_sha256:
        raise ValueError('APPROVED_ARTIFACT_CHANGED')
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    checkout = Path(tempfile.mkdtemp(prefix='reposnews-release-', dir=workspace))

    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args], text=True).strip()

    git('clone', '--quiet', 'https://github.com/'+REPO+'.git', '.')
    git('config', 'core.autocrlf', 'false')
    # Remove only tracked public artifact files; never touch domain configuration.
    for name in git('ls-files').splitlines():
        if name == 'CNAME':
            continue
        path = checkout/name
        if checkout not in path.resolve().parents or path.is_symlink():
            raise ValueError('UNSAFE_DEPLOY_CHECKOUT')
        path.unlink()
    for path in files:
        target = checkout/path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (checkout/'.nojekyll').write_text('', encoding='utf-8')
    git('add', '--all')
    if git('diff', '--cached', '--name-only'):
        git('commit', '--quiet', '-m', 'Publish approved ReposNews artifact '+approved_sha256[:12])
        git('push', '--quiet', 'origin', 'HEAD:main')
    return {'url': public_base, 'commit': git('rev-parse', 'HEAD'), 'sha256': approved_sha256}


def verify(root, base=PREVIEW):
    """Verify every static file over real HTTPS, byte for byte, without Railway."""
    root, files = artifact_files(root)
    checked = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        route = '/'+relative.removesuffix('index.html') if relative.endswith('index.html') else '/'+relative
        with urlopen(base.rstrip('/')+route, timeout=40) as response:
            if (response.status != 200 or urlsplit(response.url).netloc != urlsplit(base).netloc
                    or response.read() != path.read_bytes()):
                raise ValueError('STATIC_HTTP_OR_CONTENT_MISMATCH: '+route)
        checked += 1
    return {'ok': True, 'checked': checked, 'base': base, 'backend_required': False}
