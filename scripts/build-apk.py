"""Build a source-captured debug APK without installing it; see --help."""
from apk_build import *  # Import-safe helpers are also exercised by the fixture suite.
from apk_pipeline import build_project, repack_accepted, make_tools, DEFAULT_JDK, DEFAULT_SDK
import argparse
import shutil


def main():
    parser = argparse.ArgumentParser(description='Build captured sources into an unpublished, signer-pinned APK; atomically accept a complete bundle. Never installs.')
    parser.add_argument('--sdk', default=os.environ.get('ANDROID_SDK_ROOT', DEFAULT_SDK))
    parser.add_argument('--jdk', default=os.environ.get('JAVA_HOME', DEFAULT_JDK))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--show-accepted', action='store_true', help='Read and validate the atomic accepted bundle pointer; do not build')
    modes.add_argument('--repack-accepted', action='store_true',
                       help='Re-containerize accepted compiled payload only if all application inputs are unchanged; no compilation or dependency copy')
    options = parser.parse_args()
    root = Path(__file__).absolute().parents[1]
    if options.show_accepted:
        apk, manifest = read_accepted(root)
    else:
        node = shutil.which('node.exe') or shutil.which('node')
        if not node:
            raise BuildError('Missing Node executable')
        pipeline = repack_accepted if options.repack_accepted else build_project
        apk, manifest = pipeline(root, make_tools(options.sdk, options.jdk, node))
    print(json.dumps({'apk': apk.as_posix(), 'sha256': manifest['sha256'],
                      'signer_sha256': manifest['signer']['actual_sha256'],
                      'manifest': (apk.parent / 'build-manifest.json').as_posix(),
                      'installed': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (BuildError, OSError, ValueError) as error:
        raise SystemExit('APK build rejected (previous accepted artifacts unchanged): ' + str(error))