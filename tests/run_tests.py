#!/usr/bin/env python3
"""Build, then run the browser test against a fake Designer.

    python tests/run_tests.py

Needs: Python 3, Node 18+, and `npm install` + `npx playwright install chromium` once.
Screenshots and an exported PNG land in tests/out/.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'out')
TESTS = ['e2e.mjs']


def wait_up(port):
    for _ in range(50):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/api/session/status/session' % port, timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('mock designer did not start on %d' % port)


def main():
    subprocess.check_call([sys.executable, os.path.join(ROOT, 'build.py')])
    os.makedirs(OUT, exist_ok=True)
    failed = []
    if subprocess.call([sys.executable, os.path.join(HERE, 'test_helper.py')]):
        failed.append('test_helper.py')
    for i, test in enumerate(TESTS):
        proj = tempfile.mkdtemp(prefix='am_proj_')
        shutil.copytree(os.path.join(ROOT, 'dist', 'advanced-masker'), os.path.join(proj, 'plugins', 'advanced-masker'))
        for sub in ('VideoFile', 'DxTexture'):
            os.makedirs(os.path.join(proj, 'objects', sub))
        port = 8890 + i
        mock = subprocess.Popen([sys.executable, os.path.join(HERE, 'mock_designer.py'), proj, str(port)])
        try:
            wait_up(port)
            print('\n=== %s ===' % test, flush=True)
            r = subprocess.run(['node', os.path.join(HERE, test), str(port), OUT, proj], cwd=ROOT, timeout=240)
            if r.returncode:
                failed.append(test)
        finally:
            mock.terminate()
            mock.wait()
            shutil.rmtree(proj, ignore_errors=True)
    print('\nFAILED: ' + ', '.join(failed) if failed else '\nall tests passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
