"""Release input validation and the complete native build matrix (no builds run)."""
from scripts.build_release import validate_version


PUBLIC_REPOSITORY = 'Loukious/TikTokStreamKeyGenerator'
RELEASE_SIGNING_POLICY = 'release-signing'
RELEASE_CERTIFICATE = 'release_certificate_2026'


def native_build_matrix():
    return {'include': [
        {'os': 'windows-2025', 'platform': 'win', 'arch': 'x86_64', 'build_type': 'Release'},
        {'os': 'windows-2025', 'platform': 'win', 'arch': 'x86_64', 'build_type': 'Debug'},
        {'os': 'ubuntu-24.04', 'platform': 'linux', 'arch': 'x86_64', 'build_type': 'Release'},
        {'os': 'macos-15-intel', 'platform': 'macos', 'arch': 'x86_64', 'build_type': 'Release'},
        {'os': 'macos-15', 'platform': 'macos', 'arch': 'arm64', 'build_type': 'Release'},
    ]}


def validate_release_request(*, version, signing_policy, publish, repository, has_signpath_token,
                             allow_test_certificate_release=False):
    validate_version(version)
    if signing_policy not in ('release-signing', 'test-signing', 'unsigned'):
        raise ValueError('Unknown Windows signing policy.')
    if publish and repository != PUBLIC_REPOSITORY:
        raise ValueError('Test repositories produce workflow artifacts only; publishing is disabled.')
    test_release = signing_policy == 'test-signing' and allow_test_certificate_release
    if publish and signing_policy != RELEASE_SIGNING_POLICY and not test_release:
        raise ValueError(f'Published releases require {RELEASE_SIGNING_POLICY} using {RELEASE_CERTIFICATE}.')
    if signing_policy != 'unsigned' and not has_signpath_token:
        raise ValueError('Add the CI user token as the SIGNPATH_API_TOKEN repository secret before requesting signing.')
