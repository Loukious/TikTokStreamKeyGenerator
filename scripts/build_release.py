"""Build native Nuitka bundles; keep local credentials and DevTools out of them."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = 'TiktokStreamKeyGenerator'
MAC_FFMPEG_TAG = 'n8.1.2-1'
MAC_FFMPEG_ASSETS = {
    'arm64': ('ffmpeg-osx-arm64', 'e7b9fcd97f95f333512d6e8b8ac24d9dbc08f189f36047695499bd7b57214b22'),
    'x86_64': ('ffmpeg-osx-x64', '62c87854d851f202fc4a29bdda0fe7b6ebcddd37b863482ce1bdc81151b03fe4'),
}


def download_file(url, destination, expected_sha256=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'TikTokStreamKeyGenerator-build'})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, destination.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if expected_sha256 and digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError('FFmpeg download did not match the pinned SHA-256 digest')


def validate_version(value):
    if not re.fullmatch(r'\d{1,5}(?:\.\d{1,5}){1,3}', value) or any(int(v) > 65535 for v in value.split('.')):
        raise ValueError('Use a numeric version such as 1.1.0 (each component <= 65535).')
    return value


def nuitka_command(version, build_type, system=None):
    system = system or platform.system()
    args = [sys.executable, '-m', 'nuitka', '--assume-yes-for-downloads',
            '--standalone', '--enable-plugin=pyside6', '--show-progress',
            '--jobs=2', '--output-dir=build', '--report=build/compilation-report.xml',
            '--include-package=Libs', '--include-package=qfluentwidgets',
            '--include-package=websockets', '--include-package-data=qfluentwidgets',
            '--include-package-data=certifi', '--include-package-data=tzdata',
            '--nofollow-import-to=DevTools,tests,pytest',
            '--include-data-files=assets/app-icon.ico=assets/app-icon.ico',
            '--include-data-files=assets/app-icon.png=assets/app-icon.png']
    if system == 'Windows':
        args += ['--clang', '--windows-icon-from-ico=assets/app-icon.ico',
                 '--company-name=Loukious', '--product-name=TikTok Stream Key Generator',
                 f'--file-version={version}', f'--product-version={version}',
                 '--file-description=TikTok Stream Key Generator']
        if build_type == 'Release':
            args += ['--windows-console-mode=disable']
    elif system == 'Darwin':
        args += ['--macos-create-app-bundle', '--macos-app-icon=assets/app-icon.png',
                 f'--macos-app-version={version}', '--macos-app-name=TikTok Stream Key Generator']
    args.append('TiktokStreamKeyGenerator.py')
    return args


def bundle_path():
    return ROOT / 'build' / (APP + ('.app' if sys.platform == 'darwin' else '.dist'))


def executable_path():
    bundle = bundle_path()
    if sys.platform == 'darwin':
        return bundle / 'Contents' / 'MacOS' / APP
    return bundle / (APP + ('.exe' if sys.platform == 'win32' else '.bin'))


def add_ffmpeg(bundle):
    system = platform.system()
    if system == 'Darwin':
        asset, digest = MAC_FFMPEG_ASSETS[platform.machine()]
        url = f'https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/{MAC_FFMPEG_TAG}/{asset}'
    else:
        target = 'win64-lgpl.zip' if system == 'Windows' else 'linux64-lgpl.tar.xz'
        url = f'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-{target}'
    bin_dir = bundle / ('Contents/MacOS/bin' if system == 'Darwin' else 'bin')
    bin_dir.mkdir(parents=True, exist_ok=True)
    name = 'ffmpeg.exe' if system == 'Windows' else 'ffmpeg'
    destination = bin_dir / name
    # Extract only the binary and license documents, never arbitrary archive paths.
    license_dir = bundle / ('Contents/Resources/ffmpeg-licenses' if system == 'Darwin' else 'ffmpeg-licenses')
    license_dir.mkdir(parents=True, exist_ok=True)
    if system == 'Darwin':
        download_file(url, destination, digest)
        download_file('https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/COPYING.GPLv3', license_dir / 'COPYING.GPLv3')
        download_file(f'https://raw.githubusercontent.com/shaka-project/static-ffmpeg-binaries/{MAC_FFMPEG_TAG}/README.md',
                      license_dir / 'BUILD-README.md')
    else:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'ffmpeg.download'
            download_file(url, archive)
            if url.endswith('.zip'):
                with zipfile.ZipFile(archive) as opened:
                    files = [(info.filename, lambda i=info: opened.open(i)) for info in opened.infolist() if not info.is_dir()]
                    copy_ffmpeg_files(files, name, destination, license_dir)
            else:
                with tarfile.open(archive, 'r:xz') as opened:
                    files = [(info.name, lambda i=info: opened.extractfile(i)) for info in opened.getmembers() if info.isfile()]
                    copy_ffmpeg_files(files, name, destination, license_dir)
    if not destination.is_file():
        raise RuntimeError('FFmpeg binary was absent from the downloaded archive')
    destination.chmod(0o755)
    (license_dir / 'SOURCE.txt').write_text(f'Binary distribution: {url}\nUpstream: https://ffmpeg.org/\n', encoding='utf-8')
    subprocess.run([str(destination), '-version'], check=True)


def copy_ffmpeg_files(files, name, destination, license_dir):
    for path, open_file in files:
        basename = Path(path).name
        output = destination if basename == name else None
        if basename.lower().startswith(('license', 'copying')):
            output = license_dir / basename
        if output is not None:
            with open_file() as source, output.open('wb') as target:
                shutil.copyfileobj(source, target)


def package(version, build_type, signing):
    bundle = bundle_path()
    system = {'Windows': 'win', 'Darwin': 'macos', 'Linux': 'linux'}[platform.system()]
    arch = platform.machine().lower().replace('amd64', 'x86_64').replace('aarch64', 'arm64')
    suffix = '-test-signed' if system == 'win' and signing == 'test-signing' else ''
    if system == 'win' and signing == 'unsigned':
        suffix = '-unsigned'
    output = ROOT / 'artifacts' / f'{APP}-{build_type}-{system}-{arch}-{version}{suffix}.zip'
    output.parent.mkdir(exist_ok=True)
    # zip preserves executable mode and .app symlinks on Unix; shutil.make_archive does not.
    if os.name == 'nt':
        shutil.make_archive(str(output.with_suffix('')), 'zip', bundle)
    else:
        subprocess.run(['zip', '-qry', str(output), bundle.name], cwd=bundle.parent, check=True)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, type=validate_version)
    parser.add_argument('--build-type', choices=('Release', 'Debug'), default='Release')
    parser.add_argument('--package-only', action='store_true')
    parser.add_argument('--signing', choices=('unsigned', 'test-signing', 'release-signing'), default='unsigned')
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.package_only:
        package(args.version, args.build_type, args.signing)
        return
    (ROOT / '_version.py').write_text(f'__version__ = "{args.version}"\n', encoding='utf-8')
    subprocess.run(nuitka_command(args.version, args.build_type), check=True)
    if not executable_path().is_file():
        raise RuntimeError('Nuitka did not produce the expected executable')
    add_ffmpeg(bundle_path())
    report = ROOT / 'build' / 'smoke-test.log'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', TIKTOK_SIGNER_MODE='api',
               TIKTOK_SMOKE_REPORT=str(report))
    # A Windows GUI executable has no sys.stderr during interpreter startup.
    # The entrypoint enables faulthandler against this report file instead.
    env.pop('PYTHONFAULTHANDLER', None)
    try:
        subprocess.run([str(executable_path()), '--smoke-test'], check=True, timeout=60, env=env)
    finally:
        if report.is_file():
            print(report.read_text(encoding='utf-8', errors='replace'), flush=True)


if __name__ == '__main__':
    main()
