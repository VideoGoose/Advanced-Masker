"""Unit checks for src/designer.py that the browser test can't see (run by run_tests.py).

Designer runs the helper under Python 2, where file sizes are `long` and repr() adds an L
(123L), which is not JSON. Python 3 has no long, so a stand-in int subclass plays its part.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('am_helper', os.path.join(HERE, '..', 'src', 'designer.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class Long(int):
    def __repr__(self):
        return '%dL' % self


def main():
    fails = []
    for value in [Long(123456), {'size': Long(7), 'n': 3}, [Long(1), 2.5, True, None, u'a\\b "c"']]:
        text = helper._dumps(value)
        try:
            back = json.loads(text)
        except ValueError:
            fails.append('not JSON: ' + text)
            continue
        if back != json.loads(json.dumps(value)):
            fails.append('round trip changed %r -> %s' % (value, text))
    if helper._dumps(float('nan')) != 'null':
        fails.append('NaN should be null')
    ok = json.loads(helper._ok(images=[{'rel': 'VideoFile/a.png', 'size': Long(5000)}]))
    if ok['images'][0]['size'] != 5000:
        fails.append('_ok lost the size')
    print('helper checks:', 'FAIL\n  ' + '\n  '.join(fails) if fails else 'ok')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
