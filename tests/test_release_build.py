"""Release configuration checks that do not compile or access the network."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from scripts import build_release as build
from scripts import release_config as config


class ReleaseTests(unittest.TestCase):
    def test_versions_reject_shell_and_version_file_injection(self):
        for value in ('1.1.0', '2.0', '65535.0.1.2'):
            self.assertEqual(build.validate_version(value), value)
        for value in ('', 'v1.0', '1.0\n', '1.0;echo bad', "1.0'", '65536.0', '1.2.3.4.5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.validate_version(value)

    def test_every_release_includes_all_five_native_packages(self):
        matrix = config.native_build_matrix()['include']
        self.assertEqual({(r['platform'], r['arch'], r['build_type']) for r in matrix}, {
            ('win', 'x86_64', 'Release'), ('win', 'x86_64', 'Debug'),
            ('linux', 'x86_64', 'Release'), ('macos', 'x86_64', 'Release'),
            ('macos', 'arm64', 'Release')})
        self.assertEqual(len(matrix), 5)
        self.assertEqual([r['os'] for r in matrix if r['platform'] == 'macos'],
                         ['macos-15-intel', 'macos-15'])

    def request(self):
        return dict(version='2.2.0', signing_policy='release-signing', publish=False,
                    repository='Loukious/TestTikTok', has_signpath_token=True)

    def test_private_repository_cannot_publish_even_with_production_signing(self):
        options = self.request()
        options['publish'] = True
        with self.assertRaisesRegex(ValueError, 'publishing is disabled'):
            config.validate_release_request(**options)

    def test_publication_requires_production_policy(self):
        for policy in ('unsigned', 'test-signing'):
            options = self.request()
            options.update(repository=config.PUBLIC_REPOSITORY, publish=True, signing_policy=policy)
            with self.assertRaisesRegex(ValueError, 'release_certificate_2026'):
                config.validate_release_request(**options)
        options['signing_policy'] = 'release-signing'
        config.validate_release_request(**options)

    def test_artifact_only_test_builds_and_missing_signer_credentials(self):
        options = self.request()
        for policy in ('release-signing', 'test-signing'):
            options['signing_policy'] = policy
            config.validate_release_request(**options)
            options['has_signpath_token'] = False
            with self.assertRaisesRegex(ValueError, 'SIGNPATH_API_TOKEN'):
                config.validate_release_request(**options)
            options['has_signpath_token'] = True
        options.update(signing_policy='unsigned', has_signpath_token=False)
        config.validate_release_request(**options)
        options['signing_policy'] = 'not-a-policy'
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            config.validate_release_request(**options)

    def test_windows_build_keeps_metadata_in_debug_and_release(self):
        for kind in ('Release', 'Debug'):
            args = build.nuitka_command('1.2.3', kind, 'Windows')
            self.assertIn('--file-version=1.2.3', args)
            self.assertIn('--clang', args)
            self.assertIn('--product-name=TikTok Stream Key Generator', args)
            self.assertIn('--nofollow-import-to=DevTools,tests,pytest', args)
            self.assertEqual('--windows-console-mode=disable' in args, kind == 'Release')

    def test_ffmpeg_extracts_only_the_binary_and_licenses(self):
        import io
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            licenses = directory / 'licenses'
            licenses.mkdir()
            files = [('archive/bin/ffmpeg.exe', lambda: io.BytesIO(b'binary')),
                     ('archive/LICENSE.txt', lambda: io.BytesIO(b'license')),
                     ('../../private.txt', lambda: self.fail('Unexpected archive member read'))]
            build.copy_ffmpeg_files(files, 'ffmpeg.exe', directory / 'ffmpeg.exe', licenses)
            self.assertEqual((directory / 'ffmpeg.exe').read_bytes(), b'binary')
            self.assertEqual((licenses / 'LICENSE.txt').read_bytes(), b'license')

    def test_pinned_download_rejects_and_removes_modified_binary(self):
        import io
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'ffmpeg'
            with patch.object(build.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong binary')):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                    build.download_file('https://example.invalid/ffmpeg', target, '0' * 64)
            self.assertFalse(target.exists())

    def test_signpath_signs_our_executable_inside_the_uploaded_zip(self):
        root = ET.parse(build.ROOT / '.signpath/windows-exe.xml').getroot()
        ns = {'s': 'http://signpath.io/artifact-configuration/v1'}
        executables = root.findall('s:zip-file/s:pe-file', ns)
        self.assertEqual([node.attrib['path'] for node in executables], ['TiktokStreamKeyGenerator.exe'])
        self.assertIsNotNone(executables[0].find('s:authenticode-sign', ns))

    def test_source_uses_hosted_signer_without_private_devtools(self):
        from Libs import signing_backend
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(signing_backend.is_development())


if __name__ == '__main__':
    unittest.main()
