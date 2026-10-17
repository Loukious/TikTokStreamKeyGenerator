"""Verify the test signature with a private CA file, without changing Windows trust."""

import argparse
import hashlib
from pathlib import Path
import ssl
import subprocess
import tempfile
import urllib.request
import zipfile


VERSION = "2.13"
ARCHIVE_SHA256 = "c6d3ec8f383a6ed204503a9d4445788f2d3e71da87f3604c42e40167ad9ceb8e"
URL = (
    "https://github.com/mtrojnar/osslsigncode/releases/download/"
    f"{VERSION}/osslsigncode-{VERSION}-windows-x64-mingw.zip"
)
BINARIES = ("osslsigncode.exe", "libcrypto-3-x64.dll", "libssl-3-x64.dll", "zlib1.dll")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    certificate = (root / ".signpath/test-certificate-2026.cer").read_bytes()
    cache = root / "build/signature-tools"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"osslsigncode-{VERSION}.zip"
    if not archive.exists():
        print(f"Downloading pinned osslsigncode {VERSION} (30s network timeout)", flush=True)
        with urllib.request.urlopen(URL, timeout=30) as response:
            data = response.read(10 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
            raise RuntimeError("osslsigncode download checksum mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("Cached osslsigncode checksum mismatch")

    # Extract freshly from the verified archive, including its DLL dependencies.
    # A private directory prevents loading stale or substituted cached binaries.
    with tempfile.TemporaryDirectory(prefix="signpath-verify-") as directory:
        temp = Path(directory)
        with zipfile.ZipFile(archive) as bundle:
            for name in BINARIES:
                (temp / name).write_bytes(bundle.read(f"bin/{name}"))
        ca_file = temp / "test-ca.pem"
        ca_file.write_text(ssl.DER_cert_to_PEM_cert(certificate), encoding="ascii")
        print("Verifying PE digest and signature against the pinned test certificate (60s timeout)", flush=True)
        # Test artifacts must validate now. Their timestamp must not extend the
        # self-signed certificate's validity. The private CA has no CDP service.
        result = subprocess.run(
            [str(temp / "osslsigncode.exe"), "verify", "-in", str(args.executable.resolve()),
             "-CAfile", str(ca_file), "-require-leaf-hash", f"sha256:{hashlib.sha256(certificate).hexdigest()}",
             "-ignore-timestamp", "-ignore-cdp", "-ignore-crl"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        print(result.stdout, end="", flush=True)
        print(result.stderr, end="", flush=True)
        if result.returncode:
            raise RuntimeError(f"Test Authenticode verification failed (exit {result.returncode})")
    print("Test Authenticode signature and executable integrity verified; Windows trust unchanged.", flush=True)


if __name__ == "__main__":
    main()
