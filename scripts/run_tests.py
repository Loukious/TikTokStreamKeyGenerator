"""Run each offline test module with its own Qt application/process lifetime."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', TIKTOK_SIGNER_MODE='api', PYTHONUTF8='1')
    failures = []
    for path in sorted((root / 'tests').glob('test_*.py')):
        module = 'tests.' + path.stem
        print(f'Running {module}', flush=True)
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', module, '-v'],
                                cwd=root, env=env, timeout=180)
        if result.returncode:
            failures.append(module)
    if failures:
        raise SystemExit('Failed test modules: ' + ', '.join(failures))
    print('All offline test modules passed.', flush=True)


if __name__ == '__main__':
    main()
