"""Produce a source-only archive with an explicit allowlist and credential scan."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = {'README.md', 'LICENSE', '.gitignore', 'requirements.txt', 'requirements.lock',
       'sdk-versions.json', 'start.ps1', 'start.cmd', 'start.sh', 'VALIDATION.md'}
DIRECTORIES = {'studio', 'web', 'docs', 'tests', 'scripts', 'examples'}
SUFFIXES = {'.py', '.md', '.html', '.css', '.js', '.mjs', '.json'}
PATTERNS = [re.compile(r'e2b_[A-Za-z0-9]{20,}'), re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
            re.compile(r'\bsk-[A-Za-z0-9_-]{24,}')]


def source_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(ROOT)
        if '__pycache__' in relative.parts or any(p.startswith('.') for p in relative.parts[:-1]):
            continue
        if (len(relative.parts) == 1 and relative.name in TOP) or (
                relative.parts[0] in DIRECTORIES and (path.suffix in SUFFIXES or relative.name == 'requirements.txt')):
            yield path, relative.as_posix()


def package():
    files = list(source_files())
    secrets = []
    for config in (ROOT / '.local').rglob('config.json'):
        data = json.loads(config.read_text(encoding='utf-8'))
        private = config.with_name('config-private-fields.json')
        keys = set(json.loads(private.read_text(encoding='utf-8'))) if private.exists() else set()
        keys |= {k for k in data if any(part in k.lower() for part in ('api_key','token','password','secret'))}
        secrets.extend(data[k] for k in keys if isinstance(data.get(k),str) and data[k])
    for path, name in files:
        text = path.read_text(encoding='utf-8')
        if any(pattern.search(text) for pattern in PATTERNS) or any(s in text for s in secrets):
            raise RuntimeError('Credential scan rejected file: ' + name)
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / 'agentsphere-demo-studio.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for path, name in files:
            z.write(path, name)
    manifest = {'archive': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'files': [name for _, name in files], 'count': len(files)}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    return archive


if __name__ == '__main__':
    package()
