# SignPath setup

Organization: `6f972417-ec42-48a3-8f85-2ed3dfe07fb7`
Project slug: `TikTokStreamKeyGenerator`
Test policy: `test-signing`
Production policy: `release-signing`
Production certificate slug: `release_certificate_2026` ([certificate details](https://app.signpath.io/Web/6f972417-ec42-48a3-8f85-2ed3dfe07fb7/Certificates/9d7f1877-7a7f-446c-8c54-c7f24e99ff45))

The production policy already references this certificate. Its current status is **CSR PENDING**, so the policy remains invalid until SignPath imports the issued certificate. The workflow is prepared to use this policy by default; preparation does not submit a signing request or start a build.
GitHub artifact configuration slug: `windows-exe`

The organization invitation has been accepted. The project is linked to the GitHub.com trusted build system. Its approved repository is `Loukious/TikTokStreamKeyGenerator`. First validate CI on the private `Loukious/TestTikTok` repository; do not change the approved public repository or its releases during the test.

## Configuration

1. Add a separate artifact configuration called `windows-exe` in the existing project. Select **Custom** and paste [.signpath/windows-exe.xml](../.signpath/windows-exe.xml). Keep the original `initial` single-EXE configuration available. The root must be `<zip-file>` because `actions/upload-artifact` wraps the uploaded EXE in a ZIP.
2. Open **Users and Groups → CI builds**, confirm its email address if still pending, and generate an API token. Store it only as the GitHub Actions repository secret `SIGNPATH_API_TOKEN`. The CI user is already a submitter for `test-signing`. Never paste tokens into workflow YAML, commits, issues or logs.
3. Configure the existing [SignPath GitHub App](https://github.com/apps/signpath) installation to include `Loukious/TestTikTok`. Select only the required repository rather than granting access to all repositories. This connector rejects requests without an App token for the test repository, even when workflow read permissions are present. The workflow also declares `actions: read` and `contents: read`. The `test-signing` policy currently does not enforce the production origin policy. If the connector still disallows private testing after repository access is granted, ask SignPath to enable that arrangement rather than weakening the production policy or making the repository public.
4. When a test build is explicitly wanted, dispatch the Release workflow on TestTikTok with a numeric `version` (for example `2.2.0`), `signing_policy: test-signing`, and `publish: false`. Every run includes Windows Release/Debug, Linux x86_64, macOS Intel, and macOS Apple Silicon. The final workflow artifacts contain the downloadable ZIPs; `signpath-input-*` are only the unsigned EXE inputs.
5. For production, select `release-signing` only after `release_certificate_2026` is issued and the policy is valid. Publishing is restricted to the approved public repository, after all tests and all five native packages succeed. The private test repository cannot publish. The `prerelease` checkbox only marks the GitHub release; it never weakens the production signing requirement.

Signing failures stop packaging. Test signing uses [osslsigncode](https://github.com/mtrojnar/osslsigncode) 2.13 to verify the PE digest, cryptographic signature, current certificate validity and exact signer certificate SHA-256 against the pinned [public test certificate](../.signpath/test-certificate-2026.cer). The Windows verification tool is downloaded from its official release with a pinned archive SHA-256 and used only during CI; it is not bundled with the app. Its private CA file never changes Windows certificate stores or opens trust confirmation dialogs. Test verification ignores timestamps and revocation downloads because the pinned self-signed test certificate has no revocation service; the certificate must be valid now. Production signing still requires Windows Authenticode status `Valid` with normal trust and timestamp checks, and rejects the test certificate. Verification subprocesses and workflow steps have explicit time limits.

The workflow also tests the real signed output with a changed byte in a PE section: the modified EXE must be rejected, and the trust store must remain unchanged after both successful and failed verification. When SignPath rotates the test certificate, replace the pinned public `.cer` file after checking its identity in SignPath. The 2026 certificate's SHA-256 fingerprint is `E9D0619A501020DB468D7B4B2492B25E9C461AE4AFAB9B3266628945C6D3FAD8`; this file contains no private key.

Builds pin Nuitka 4.2.2 because 4.3 has a [compiled PySide6 callback regression](https://github.com/Nuitka/Nuitka/issues/4081). The packaged startup check creates Fluent controls and runs the Qt event loop so this failure is caught before signing or publishing. Retest all native builds before upgrading the compiler.

## Production rollout

After SignPath reviews the setup and imports a production certificate, apply the tested commits to the approved repository and add its own CI secret. Verify the production policy's submitter, approval and origin restrictions. Run a production-signing build with publication disabled first. Publish only after checking the signed downloads; every publication requires all five native packages and production signing. The test repository is explicitly blocked from publishing.

SignPath signs the Windows app EXE only. macOS bundles remain unnotarized and use the README's quarantine FAQ. Code signing identifies the publisher and protects file integrity; it does not guarantee SmartScreen reputation or antivirus acceptance.

References: [Artifact configuration](https://docs.signpath.io/artifact-configuration/), [GitHub integration](https://docs.signpath.io/trusted-build-systems/github), [ZIP examples](https://docs.signpath.io/artifact-configuration/examples).
