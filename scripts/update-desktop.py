"""Manual Git-object Desktop source review; never apply or promote a candidate."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata

STATUS = 'review-only; compatibility and parity unverified'


def safe_name(name):
    if (not isinstance(name, str) or not name or name.startswith('/')
            or any(c in name for c in '\\:<>"|?*') or any(ord(c) < 32 for c in name)
            or unicodedata.normalize('NFC', name) != name):
        raise ValueError('Unsafe path: ' + repr(name))
    for part in name.split('/'):
        if (part in ('', '.', '..') or part.casefold() == '.git' or part.endswith((' ', '.'))
                or re.fullmatch(r'(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', part, re.I)):
            raise ValueError('Unsafe path: ' + repr(name))
    return name


def guarded(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Traversal rejected')
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Link/reparse target rejected: ' + str(item))
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError('Non-directory ancestor: ' + str(item))
    return path


def distinct_paths(names):
    seen, files = {}, set(names)
    for name in files:
        parts = safe_name(name).split('/')
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i])
            folded = prefix.casefold()
            if folded in seen and seen[folded] != prefix or i < len(parts) and prefix in files:
                raise ValueError('Path collision: ' + name)
            seen[folded] = prefix


def read_json(path):
    return json.loads(guarded(path).read_bytes())


def git(repo, *args, data=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-C', str(repo), *args], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
    if result.returncode:
        raise ValueError('Git object read failed: ' + result.stderr.decode('utf-8', 'replace').strip())
    return result.stdout


def resolve(repo, ref):
    if re.fullmatch(r'[0-9a-fA-F]+', ref):
        if len(ref) not in (40, 64):
            raise ValueError('Use a full 40/64-hex commit identifier, not an abbreviation')
    elif ref != 'HEAD':
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', ref):
            raise ValueError('Ref must be HEAD, a full hash, or a literal ref name')
        git(repo, 'check-ref-format', '--allow-onelevel', ref)
    commit = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise ValueError('Expected exactly one commit object')
    return commit


def tree(repo, commit):
    result = {}
    for row in git(repo, 'ls-tree', '-r', '-l', '-z', '--full-tree', commit).split(b'\0'):
        if row:
            header, raw_name = row.split(b'\t', 1)
            mode, kind, oid, size = header.decode('ascii').split()
            name = raw_name.decode('utf-8', 'strict')
            if name in result:
                raise ValueError('Duplicate Git tree path: ' + name)
            result[name] = (mode, kind, oid, int(size) if size != '-' else 0)
    return result


def blobs(repo, inventory):
    unique = {entry[2]: entry[3] for entry in inventory.values()}
    if sum(unique.values()) > 128 * 1024 * 1024 or any(n > 16 * 1024 * 1024 for n in unique.values()):
        raise ValueError('Candidate exceeds 16 MiB/blob or 128 MiB total review limit')
    stream = io.BytesIO(git(repo, 'cat-file', '--batch', data=''.join(x + '\n' for x in unique).encode()))
    result = {}
    for oid, size in unique.items():
        if stream.readline() != f'{oid} blob {size}\n'.encode():
            raise ValueError('Invalid Git blob batch header')
        payload = stream.read(size)
        if len(payload) != size or stream.read(1) != b'\n':
            raise ValueError('Truncated Git blob batch')
        result[oid] = payload
    if stream.read(1):
        raise ValueError('Unexpected Git batch tail')
    return {name: result[entry[2]] for name, entry in inventory.items()}


def owned_roots(inventory, mapped):
    """Expand only baseline directories whose entire tracked inventory was mapped."""
    counts, approved = {}, {}
    for name in inventory:
        parts = name.split('/')
        for i in range(1, len(parts)):
            parent = '/'.join(parts[:i])
            counts[parent] = counts.get(parent, 0) + 1
            approved[parent] = approved.get(parent, 0) + (name in mapped)
    roots = []
    for parent in sorted(counts, key=lambda p: (p.count('/'), p)):
        if counts[parent] == approved[parent] and not any(parent.startswith(r + '/') for r in roots):
            roots.append(safe_name(parent))
    return sorted(roots)


def difference(old, new, names):
    return dict(added=sorted(n for n in names if n not in old and n in new),
                changed=sorted(n for n in names if n in old and n in new and old[n] != new[n]),
                deleted=sorted(n for n in names if n in old and n not in new))


def inspect(project, upstream, ref):
    project, upstream = guarded(project), guarded(upstream)
    manifest = read_json(project / 'vendor/hermes/source-manifest.json')
    provenance = read_json(project / 'docs/evidence/source-provenance.json')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', manifest['commit']):
        raise ValueError('Provenance needs a full literal commit pin')
    base = resolve(upstream, manifest['commit'])
    if provenance['upstream_commit'] != base:
        raise ValueError('Provenance pins disagree')
    mapping = {}
    for entry in manifest['files']:
        source, target = safe_name(entry['source']), safe_name(entry['path'])
        if target != 'vendor/hermes/' + source:
            raise ValueError('Unsupported vendor mapping: ' + target)
        mapping.setdefault(source, []).append((target, entry['sha256']))
    for target, entry in provenance['vendored_files_byte_verified'].items():
        if not safe_name(target).startswith('src/upstream/'):
            raise ValueError('Unsupported transport mapping')
        mapping.setdefault(safe_name(entry['upstream_path']), []).append((target, entry['sha256']))
    commit = resolve(upstream, ref)
    old, new = tree(upstream, base), tree(upstream, commit)
    targets = [target for entries in mapping.values() for target, _ in entries]
    if len(targets) != len(set(targets)) or not mapping:
        raise ValueError('Duplicate/empty provenance mapping')
    distinct_paths(targets)
    if any(old[n][0] not in ('100644', '100755') or old[n][1] != 'blob' for n in mapping if n in old):
        raise ValueError('Unsafe provenance source')
    baseline = blobs(upstream, {n: old[n] for n in mapping if n in old})
    issues = dict(missingFromPinnedGit=sorted(set(mapping) - old.keys()),
                  hashMismatch=sorted(n for n, entries in mapping.items() if n in baseline and any(
                      hashlib.sha256(baseline[n]).hexdigest() != digest for _, digest in entries)))
    roots = owned_roots(old, mapping)
    scoped = set(mapping) | {n for n in old.keys() | new.keys()
                             if any(n == r or n.startswith(r + '/') for r in roots)}
    selected = {n: new[n] for n in sorted(scoped) if n in new}
    distinct_paths(selected)
    for name, entry in selected.items():
        safe_name(name)
        if entry[0] not in ('100644', '100755') or entry[1] != 'blob':
            raise ValueError('Unsafe Git tree entry: ' + name)
    payload = blobs(upstream, selected)
    files = [dict(source=name, path='source/' + name, bytes=len(data),
                  sha256=hashlib.sha256(data).hexdigest(),
                  mappedTargets=[x[0] for x in mapping.get(name, [])])
             for name, data in sorted(payload.items())]
    changes = difference(old, new, scoped)
    changes['deleted'] = sorted(set(changes['deleted']) | (set(mapping) - new.keys()))
    outside = difference(old, new, (old.keys() | new.keys()) - scoped)
    all_changes = sorted({n for group in (changes, outside) for values in group.values() for n in values})
    report = dict(schemaVersion=1, status=STATUS, requestedRef=ref, baseCommit=base,
                  candidateCommit=commit, installedRendererFingerprint=None, sourceRoots=roots, provenanceIssues=issues,
                  reviewRequired=dict(compatibility=True, dependencies=True, licenses=True),
                  reviewSignals=dict(dependencies=[n for n in all_changes if re.search(
                      r'(^|/)(package(?:-lock)?\.json|.*lock.*|.*requirements.*|pyproject\.toml|.*\.csproj)$', n, re.I)],
                      licenses=[n for n in all_changes if re.search(r'(^|/)(license|copying|notice|third.party)', n, re.I)]),
                  outsideScopeChanges=outside, changes=changes, files=files)
    return report, payload


def stage(project, destination, report, payload):
    if any(report['provenanceIssues'].values()):
        raise ValueError('Cannot stage: baseline provenance disagrees with pinned Git objects')
    project = guarded(project)
    relative = safe_name(destination)
    if not relative.startswith('.cache/'):
        raise ValueError('Stage must be a new directory below this project\'s .cache/')
    target = guarded(project / relative)
    if target.exists():
        raise ValueError('Refusing existing stage directory')
    # No cleanup/promotion: an interrupted directory is incomplete and cannot be reused.
    target.parent.mkdir(parents=True, exist_ok=True)
    guarded(target).mkdir()
    report['stage'] = relative
    manifest = {k: report[k] for k in ('schemaVersion', 'status', 'baseCommit', 'candidateCommit',
                                     'installedRendererFingerprint', 'files')}
    outputs = {'source/' + name: data for name, data in payload.items()}
    outputs.update({'manifest.json': (json.dumps(manifest, indent=2) + '\n').encode(),
                    'diff-report.json': (json.dumps(report, indent=2) + '\n').encode()})
    for name, data in outputs.items():
        path = guarded(target / safe_name(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        with guarded(path).open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    default = next((p for p in Path(__file__).absolute().parents
                    if (p / 'vendor/hermes/source-manifest.json').is_file()), None)
    parser.add_argument('--project', type=Path, default=default, help='project root (normally auto-detected)')
    parser.add_argument('--upstream', type=Path, required=True, help='explicit local Git repository; never fetched')
    parser.add_argument('--ref', default='HEAD', help='HEAD, full commit hash, or literal branch/tag/ref; no revision expressions')
    parser.add_argument('--stage', metavar='PROJECT_RELATIVE_DIR',
                        help='opt-in NEW directory under .cache/; no active files are replaced')
    args = parser.parse_args()
    try:
        if args.project is None:
            raise ValueError('Cannot locate project; supply --project')
        report, payload = inspect(args.project, args.upstream, args.ref)
        if args.stage is not None:
            stage(args.project, args.stage, report, payload)
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 1 if any(report['provenanceIssues'].values()) else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
