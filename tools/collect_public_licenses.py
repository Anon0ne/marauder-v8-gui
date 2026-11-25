"""Collect installed, pinned build-dependency notices for public distribution."""
import importlib.metadata as metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'build/public-licenses'
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for line in (ROOT / 'requirements-build.lock').read_text().splitlines():
        if '==' not in line or line.startswith('#'):
            continue
        name, expected = line.split('==', 1)
        dist = metadata.distribution(name)
        if dist.version != expected:
            raise SystemExit(f'Unexpected {name} version: {dist.version}; expected {expected}')
        notices = []
        for item in dist.files or []:
            if not Path(str(item)).name.lower().startswith(('license', 'licence', 'copying', 'notice')):
                continue
            source = Path(dist.locate_file(item))
            if not source.is_file():
                continue
            target = out / name / Path(str(item)).name
            target.parent.mkdir(exist_ok=True)
            # Avoid silently overwriting multiple distinct notices with one basename.
            if target.exists() and target.read_bytes() != source.read_bytes():
                target = target.with_name(str(len(notices)) + '-' + target.name)
            target.write_bytes(source.read_bytes())
            notices.append(str(target.relative_to(out)))
        entries.append({'name': name, 'version': dist.version,
                        'license_expression': dist.metadata.get('License-Expression'),
                        'license_classifiers': [c for c in dist.metadata.get_all('Classifier', []) if c.startswith('License ::')],
                        'notice_files': notices,
                        'project_urls': dist.metadata.get_all('Project-URL', [])})
    for pattern in ('LICENSE.txt', 'LICENSE', 'tcl/tcl*/license.terms', 'tcl/tk*/license.terms'):
        for source in Path(sys.base_prefix).glob(pattern):
            if source.is_file():
                target = out / 'Python-Tcl-Tk' / source.relative_to(sys.base_prefix)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    (out / 'inventory.json').write_text(json.dumps(entries, indent=2) + '\n', encoding='utf-8')
    (out / 'README.txt').write_text(
        'Installed dependency metadata and available notice files for this build.\n'
        'Components retain their original copyrights and licenses.\n'
        'This inventory does not replace license terms or certify legal compliance.\n', encoding='utf-8')
    print(f'Collected notice inventory for {len(entries)} pinned packages')


if __name__ == '__main__':
    main()
