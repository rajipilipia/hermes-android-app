"""Shared APK build boundaries. Only the CLI entry point launches real tools."""
from pathlib import Path
import json
import os
import uuid
import stat
import hashlib
import io
import re
import zipfile
import unicodedata
import struct
from concurrent.futures import ThreadPoolExecutor
from itertools import islice

APK_NAME = 'hermes-android-prototype-debug.apk'
PACKAGE = 'us.pilipia.hermes.prototype'


def read_pin(root, path):
    text = read_guarded(root, path).decode('ascii')
    if not re.fullmatch(r'[0-9a-f]{64}(?:\r?\n)?', text):
        raise BuildError('Malformed trusted certificate SHA-256 pin')
    return text[:64]


def verify_signer(output, expected):
    lines = output.splitlines()
    counts = [line for line in lines if line.startswith('Number of signers:')]
    records = [line for line in lines if 'certificate SHA-256 digest:' in line]
    # SDK 37 labels the single v3 signer by scheme; older tools number it.
    # Parse whole records, not any digest buried in unrelated certificate text.
    match = re.fullmatch(
        r'(?:Signer #1|V3\.0 Signer:) certificate SHA-256 digest: ([0-9a-fA-F]{64})',
        records[0]) if len(records) == 1 else None
    if (counts and counts != ['Number of signers: 1']) or not match or match.group(1).lower() != expected:
        raise BuildError('Candidate signer differs from trusted certificate pin')
    return expected


def archive_name(name):
    if (not name or name.startswith('/') or '\\' in name or ':' in name or '\x00' in name
            or any(p in ('', '.', '..') for p in name.split('/'))
            or unicodedata.normalize('NFC', name) != name):
        raise BuildError('Noncanonical archive destination: ' + repr(name))
    return name


def zip_payload(root, path, *, metadata=False):
    contents, compressions, folded = {}, {}, set()
    with zipfile.ZipFile(io.BytesIO(read_guarded(root, path))) as archive:
        for item in archive.infolist():
            name = archive_name(item.filename.rstrip('/') if item.is_dir() else item.filename)
            key = name.casefold()
            if key in folded:
                raise BuildError('duplicate/collision archive destination: ' + name)
            folded.add(key)
            if item.is_dir():
                continue
            if _is_link(type('ZipMode', (), {'st_mode': item.external_attr >> 16})()):
                raise BuildError('Symlink ZIP entry rejected: ' + name)
            contents[name] = archive.read(item)
            compressions[name] = item.compress_type
    return (contents, compressions) if metadata else contents


def package_unsigned(root, source, base, dex, target, *, expected_inputs=None, expected_dist=None):
    """Bind actual copied bytes, not a subsequent read of live dist/native assets."""
    source = Path(source)
    entries, compressions = zip_payload(root, base, metadata=True)
    folded = {name.casefold() for name in entries}
    def add(name, path):
        archive_name(name)
        if name.casefold() in folded:
            raise BuildError('duplicate/collision archive destination: ' + name)
        folded.add(name.casefold())
        data = read_guarded(root, path)
        if name.startswith('assets/www/') and expected_dist is not None:
            if expected_dist.get(name.removeprefix('assets/www/')) != sha256(data):
                raise BuildError('Generated dist output binding differs from captured bytes: ' + name)
        elif name.startswith('assets/') and expected_inputs is not None:
            if expected_inputs.get(Path(path).relative_to(source).as_posix()) != sha256(data):
                raise BuildError('Packaged source binding differs from captured input: ' + name)
        entries[name] = data
    dexes = [p for p in tree_files(root, dex) if p.suffix == '.dex']
    if not any(p.name == 'classes.dex' for p in dexes):
        raise BuildError('Missing generated classes.dex')
    for file in dexes:
        add(file.name, file)
    dist = source / 'dist'
    if not guard(root, dist / 'index.html', kind='file'):
        raise BuildError('Missing generated web entry point')
    for file in tree_files(root, dist):
        add('assets/www/' + file.relative_to(dist).as_posix(), file)
    native = source / 'android/assets'
    if guard(root, native).exists():
        for child in native.iterdir():
            guard(root, child)
            if child.name.casefold() in ('www', 'license.upstream', 'third_party_notices.md'):
                raise BuildError('Native asset uses reserved namespace: ' + child.name)
        for file in tree_files(root, native):
            relative = file.relative_to(native).as_posix()
            if relative.split('/')[0].casefold() in ('www', 'license.upstream', 'third_party_notices.md'):
                raise BuildError('Native asset uses reserved namespace: ' + relative)
            add('assets/' + relative, file)
    for name in ('LICENSE.upstream', 'THIRD_PARTY_NOTICES.md'):
        add('assets/' + name, source / name)
    # All validation precedes creating a destination (including duplicate checks).
    target = guard(root, target)
    mkdir_guarded(root, target.parent)
    try:
        with target.open('xb') as stream, zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data, compress_type=(zipfile.ZIP_STORED if name == 'resources.arsc'
                                                         else compressions.get(name, zipfile.ZIP_DEFLATED)))
    except FileExistsError as error:
        raise BuildError('Refusing existing generated destination') from error
    return {name: sha256(data) for name, data in sorted(entries.items())}


def verify_layout(root, path):
    """Android R+ requires stored resources.arsc with 4-byte local data alignment.

    Central-directory extra fields need not match local ones (zipalign changes
    local padding). Never derive this offset from ZipInfo.extra.
    """
    data = read_guarded(root, path)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        tables = [info for info in archive.infolist() if info.filename == 'resources.arsc']
        if len(tables) != 1:
            raise BuildError('Missing/duplicate resources.arsc layout record')
        info = tables[0]
        offset = info.header_offset
        if offset < 0 or data[offset:offset + 4] != b'PK\x03\x04' or offset + 30 > len(data):
            raise BuildError('Invalid resource-table local ZIP header')
        flags, compression = struct.unpack_from('<HH', data, offset + 6)
        name_length, extra_length = struct.unpack_from('<HH', data, offset + 26)
        start = offset + 30 + name_length + extra_length
        if (data[offset + 30:offset + 30 + name_length] != b'resources.arsc'
                or flags != info.flag_bits or flags & 1 or compression != info.compress_type
                or start + info.compress_size > archive.start_dir):
            raise BuildError('Inconsistent resource-table local ZIP header')
        if compression != zipfile.ZIP_STORED:
            raise BuildError('resources.arsc must be stored uncompressed')
        if start % 4:
            raise BuildError('resources.arsc data is not aligned on a 4-byte boundary')
        return {'resources.arsc': {'compression': 'stored', 'data_offset': start,
                                   'alignment': 4, 'bytes': info.file_size}}


def signature_entry(name):
    return bool(re.fullmatch(r'META-INF/(MANIFEST\.MF|[A-Za-z0-9_-]+\.(SF|RSA|DSA|EC))', name))


def repack_unsigned(root, prior, target, expected):
    """Copy payload bytes only; discard recognized v1 signatures and ZIP signing block.

    Reconstructing a ZIP naturally discards the non-entry v2/v3 signing block.
    Preserve every other entry's compression intent except resources.arsc.
    """
    entries, compressions = zip_payload(root, prior, metadata=True)
    if {name: sha256(data) for name, data in entries.items()} != expected:
        raise BuildError('Prior APK entries differ from accepted manifest')
    for name in entries:
        if not (signature_entry(name) or name in ('AndroidManifest.xml', 'resources.arsc')
                or re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name)
                or name.startswith(('assets/', 'res/'))):
            raise BuildError('Unknown prior APK payload namespace: ' + name)
    if not {'AndroidManifest.xml', 'resources.arsc', 'classes.dex'}.issubset(entries):
        raise BuildError('Prior APK is missing required compiled payload')
    payload = {name: data for name, data in entries.items() if not signature_entry(name)}
    target = guard(root, target)
    mkdir_guarded(root, target.parent)
    try:
        with target.open('xb') as stream, zipfile.ZipFile(stream, 'w') as archive:
            for name, data in sorted(payload.items()):
                archive.writestr(name, data, compress_type=(zipfile.ZIP_STORED if name == 'resources.arsc'
                                                         else compressions[name]))
    except FileExistsError as error:
        raise BuildError('Refusing existing repack output') from error
    return {name: sha256(data) for name, data in sorted(payload.items())}


def verify_zip(root, path, expected):
    entries = {name: sha256(data) for name, data in zip_payload(root, path).items()}
    payload = {name: digest for name, digest in entries.items() if not signature_entry(name)}
    if payload != expected:
        raise BuildError('Candidate ZIP entries differ from captured package outputs')
    return entries


SOURCE_DIRS = ('src', 'android', 'vendor', 'public', 'tests', 'docs')
REQUIRED_FILES = ('package.json', 'package-lock.json', 'index.html', 'vite.config.ts',
                  'tsconfig.json', 'LICENSE.upstream', 'THIRD_PARTY_NOTICES.md',
                  'scripts/build-apk.py', 'scripts/apk_build.py', 'scripts/apk_pipeline.py',
                  'scripts/test-native.py', 'android/signing-certificate.sha256')
OPTIONAL_FILES = ('.gitignore', 'README.md', 'AGENTS.md', 'CHANGELOG.md', '.env.example')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def tree_files(root, directory, *, exclude=()):
    directory = guard(root, directory, kind='dir')
    found = []
    def visit(current):
        for child in sorted(current.iterdir()):
            relative = child.relative_to(directory).as_posix()
            if any(relative == x or relative.startswith(x + '/') for x in exclude):
                continue
            guard(root, child)
            mode = child.stat().st_mode
            if stat.S_ISDIR(mode):
                visit(child)
            elif stat.S_ISREG(mode):
                found.append(child)
            else:
                raise BuildError('Nonregular input rejected: ' + str(child))
    visit(directory)
    return found


def source_paths(root):
    root = Path(root)
    paths = set(REQUIRED_FILES)
    for name in REQUIRED_FILES:
        guard(root, root / name, kind='file')
    for name in OPTIONAL_FILES:
        path = guard(root, root / name)
        if path.exists():
            paths.add(name)
    for name in SOURCE_DIRS:
        directory = guard(root, root / name)
        if directory.exists():
            paths.update(p.relative_to(root).as_posix() for p in tree_files(root, directory))
    return sorted(paths)


def hash_files(root, names):
    def measure(name):
        return name, sha256(read_guarded(root, Path(root) / name))
    return dict(_file_map(measure, sorted(names)))


def _file_map(function, names):
    """Overlap blocking file I/O; keep eight workers and at most 64 queued files.

    Ordered results preserve receipts. Executor teardown joins admitted work even
    when a file fails, before callers can reject or publish a build.
    """
    pending = iter(names)
    with ThreadPoolExecutor(max_workers=8) as executor:
        while True:
            batch = list(islice(pending, 64))
            if not batch:
                return
            yield from executor.map(function, batch)


def capture_files(root, destination, names, *, durable=True, verify=True):
    """Copy files and return their hashes.

    durable=False skips the per-file fsync (dependency copies are rebuildable, and one
    fsync per file cost about 10 minutes for 40,000 files). verify=False skips the second
    read of the originals; callers that use it must check the copy later (see fingerprints).
    """
    destination = mkdir_guarded(root, destination)
    names = sorted(names)
    def capture(name):
        data = read_guarded(root, Path(root) / name)
        write_new(root, destination / name, data, durable=durable)
        return name, sha256(data)
    captured = dict(_file_map(capture, names))
    if verify and captured != hash_files(root, names):
        raise BuildError('source inputs changed while capturing')
    return captured


def fingerprint_files(root, names):
    """Size and mtime of each file: a cheap endpoint check for rebuildable copies.

    Any in-place write changes mtime or size. Full content hashes stay in the manifest.
    """
    def measure(name):
        info = guard(root, Path(root) / name, kind='file').stat()
        return name, (info.st_size, info.st_mtime_ns)
    return dict(_file_map(measure, sorted(names)))


def check_fingerprints(root, expected):
    actual = fingerprint_files(root, expected)
    changed = sorted(name for name in expected if actual[name] != expected[name])
    if changed:
        raise BuildError('Captured inputs changed (size/mtime): ' + ', '.join(changed[:12]))


def check_hashes(root, expected):
    actual = hash_files(root, expected)
    changed = sorted(name for name in expected if actual[name] != expected[name])
    if changed:
        raise BuildError('Captured inputs changed: ' + ', '.join(changed[:12]))



def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def guard(root, path, *, kind=None):
    """Reject lexical escapes, symlinks and Windows reparse points at every level.

    This is an accidental/untrusted input-path boundary, not a sandbox against
    hostile concurrent filesystem mutation or executable build configuration.
    """
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise BuildError('Path escapes project: ' + str(path)) from error
    if any(part in ('..', '.') or ':' in part for part in relative.parts):
        raise BuildError('Noncanonical path: ' + str(path))
    for ancestor in reversed(root.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if _is_link(info):
            raise BuildError('Symlink/reparse project ancestor rejected: ' + str(ancestor))
    current = root
    info = None
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            info = None
            continue
        if _is_link(info):
            raise BuildError('Symlink/reparse point rejected: ' + str(current))
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise BuildError('Path ancestor is not a directory: ' + str(current))
    # Canonical lexical containment plus rejection of every ancestor reparse point
    # already establishes physical containment. resolve() would re-walk all paths
    # twice per file (and obscure which reparse entry was rejected).
    if kind == 'file' and (info is None or not stat.S_ISREG(info.st_mode)):
        raise BuildError('Missing/nonregular input: ' + str(path))
    if kind == 'dir' and (info is None or not stat.S_ISDIR(info.st_mode)):
        raise BuildError('Missing directory: ' + str(path))
    return path


def read_guarded(root, path):
    path = guard(root, path, kind='file')
    before = path.stat()
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise BuildError('Input replaced before open: ' + str(path))
        data = stream.read()
    after = guard(root, path, kind='file').stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise BuildError('Input changed while reading: ' + str(path))
    return data


def mkdir_guarded(root, path):
    path = guard(root, path)
    path.mkdir(parents=True, exist_ok=True)
    return guard(root, path, kind='dir')


def write_new(root, path, data, *, durable=True):
    path = guard(root, path)
    mkdir_guarded(root, path.parent)
    try:
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
    except FileExistsError as error:
        raise BuildError('Refusing existing generated destination: ' + str(path)) from error
    guard(root, path, kind='file')
    return path



class BuildError(RuntimeError):
    pass


def validate_bundle(root, candidate):
    actual_names = {p.relative_to(candidate).as_posix() for p in tree_files(root, candidate)}
    if actual_names != {APK_NAME, 'build-manifest.json', 'SHA256SUMS'}:
        raise BuildError('Unexpected candidate bundle outputs')
    manifest_bytes = read_guarded(root, Path(candidate) / 'build-manifest.json')
    try:
        manifest = json.loads(manifest_bytes)
        apk = read_guarded(root, Path(candidate) / APK_NAME)
        checksum = read_guarded(root, Path(candidate) / 'SHA256SUMS')
        if (manifest['schema'] != 2 or manifest['apk'] != APK_NAME
                or manifest['package'] != PACKAGE or manifest['sha256'] != sha256(apk)
                or manifest['bytes'] != len(apk)
                or manifest['signer']['actual_sha256'] != manifest['signer']['expected_sha256']
                or not re.fullmatch(r'[0-9a-f]{64}', manifest['signer']['expected_sha256'])
                or checksum != (sha256(apk) + '  ' + APK_NAME + '\n').encode()):
            raise BuildError('Candidate bundle integrity/hash mismatch')
    except (KeyError, TypeError, ValueError) as error:
        raise BuildError('Invalid bundle manifest') from error
    return manifest, sha256(manifest_bytes)


def read_accepted(root):
    root = Path(root)
    pointer = json.loads(read_guarded(root, root / 'artifacts/accepted-apk.json'))
    relative = pointer.get('bundle', '')
    if pointer.get('schema') != 1 or not re.fullmatch(r'apk-builds/[0-9a-f]{32}', relative):
        raise BuildError('Invalid accepted APK pointer')
    bundle = guard(root, root / 'artifacts' / relative, kind='dir')
    manifest, digest = validate_bundle(root, bundle)
    if pointer.get('manifest_sha256') != digest or pointer.get('apk_sha256') != manifest['sha256']:
        raise BuildError('Accepted pointer/bundle hash mismatch')
    return bundle / APK_NAME, manifest


def publish_accepted(root, candidate, validate, *, replace=os.replace):
    """Publish a complete immutable bundle via one atomic pointer, never legacy aliases.

    An interruption before pointer replacement leaves the previous pointer valid.
    Unreferenced bundles are not accepted. Readers must use read_accepted().
    """
    root, candidate = Path(root), Path(candidate)
    guard(root, candidate, kind='dir')
    validate()
    manifest, manifest_digest = validate_bundle(root, candidate)
    out = mkdir_guarded(root, root / 'artifacts')
    guard(root, out / 'accepted-apk.json')
    bundles = mkdir_guarded(root, out / 'apk-builds')
    identity = uuid.uuid4().hex
    bundle = guard(root, bundles / identity)
    if bundle.exists():
        raise BuildError('Bundle destination exists')
    replace(candidate, bundle)
    pointer = out / ('.accepted-' + identity + '.tmp')
    write_new(root, pointer, (json.dumps({'schema': 1, 'bundle': 'apk-builds/' + identity,
                                        'manifest_sha256': manifest_digest,
                                        'apk_sha256': manifest['sha256']}) + '\n').encode())
    try:
        guard(root, out / 'accepted-apk.json')
        replace(pointer, out / 'accepted-apk.json')
    finally:
        guard(root, pointer).unlink(missing_ok=True)
    return bundle
