#!/usr/bin/env python3
"""Assemble dist/advanced-masker/ -- the folder that goes in {project}/plugins/.

    python build.py                             # build only
    python build.py --install "<plugins dir>"   # build, copy into a Designer project's plugins
                                                # folder, and byte-check the copy
    python build.py --zip                       # build + dist/advanced-masker-<version>.zip
"""
import base64
import filecmp
import io
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
PLUGIN = 'advanced-masker'     # plugins/<PLUGIN>/ ; the window tells the helper which folder it is in
OUT = os.path.join(HERE, 'dist', PLUGIN)
VERSION = '0.1.6'   # bump the last number on every change you install
# replaced on every install / update. The user's mask sets (masks/) are never part of a build.
FILES = ['index.html', 'out.html', '__init__.py', 'd3plugin.json', 'VERSION.txt', 'README.txt', 'icon.svg', 'LICENSE.txt']

PLUGIN_README = """Advanced Masker v{v} for disguise Designer
==========================================

Install / update
  1. Unzip so this folder sits at  <your Designer project>\\plugins\\advanced-masker\\
  2. In Designer: Plugins > Plugin Launcher > Advanced Masker.
     After an update, close the plugin window and open it again.
  Updating replaces only the plugin's own files. Your saved mask sets are never part of an update.

What it does
  Draw masks with a pen tool, stack them as layers you can turn on and off,
  size the canvas from a mapping, show the result live on a Web layer, and
  save it as a PNG or TIF into the project.

Your files in this folder
  masks\\   saved mask sets, one .json each. Copy a file into another project's
            advanced-masker\\masks\\ folder to use it there.

Exports (Save PNG / Save TIF) go to
  <project>\\objects\\VideoFile\\masks\\   or   <project>\\objects\\DxTexture\\masks\\
"""


def read(name):
    with open(os.path.join(SRC, name), encoding='utf-8') as f:
        return f.read()


def build():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, 'masks'))
    mask = read('mask.js')
    py = read('designer.py').replace('@VERSION@', VERSION)
    assert '</script' not in mask.lower() and '</script' not in py.lower()
    with open(os.path.join(HERE, 'assets', 'icon.svg'), 'rb') as f:
        icon = base64.b64encode(f.read()).decode('ascii')     # header logo + favicon, inlined
    index = read('index.src.html').replace('@VERSION@', VERSION).replace('/*@MASK@*/', mask) \
                                  .replace("/*@PYSRC@*/''", json.dumps(py)).replace('@ICON_B64@', icon)
    out = read('out.src.html').replace('/*@MASK@*/', mask).replace('@VERSION@', VERSION)
    assert '@MASK@' not in index + out and '@PYSRC@' not in index and '@ICON_B64@' not in index
    assert '@VERSION@' not in index + out + py
    files = {
        'index.html': index,
        'out.html': out,
        '__init__.py': py,     # Designer auto-loads this; the window also registers it fresh
        'd3plugin.json': json.dumps({'name': 'Advanced Masker v' + VERSION, 'requiresSession': True}, indent=2) + '\n',
        'VERSION.txt': VERSION + '\n',
        'README.txt': PLUGIN_README.format(v=VERSION),
        # Designer's Plugin Launcher loads <plugin url>/icon.svg and draws it at 24 x 24 px
        'LICENSE.txt': io.open(os.path.join(HERE, 'LICENSE'), encoding='utf-8').read(),
        'icon.svg': io.open(os.path.join(HERE, 'assets', 'launcher-icon.svg'), encoding='utf-8').read(),
        'masks/put-mask-sets-here.txt': ('Save set in the plugin window writes <name>.json here.\n'
                                         'Copy a .json file into another project\'s plugins/advanced-masker/masks/ folder to use it there.\n'),
    }
    for name, text in files.items():
        nl = '\r\n' if name.endswith('.txt') and name != 'VERSION.txt' else '\n'
        with open(os.path.join(OUT, name), 'w', encoding='utf-8', newline=nl) as f:
            f.write(text)
    print('built v%s ->' % VERSION, OUT)
    for name in sorted(files):
        print('  %-34s %7d bytes' % (name, os.path.getsize(os.path.join(OUT, name))))


def install(plugins_dir):
    dest = os.path.join(plugins_dir, PLUGIN)
    os.makedirs(os.path.join(dest, 'masks'), exist_ok=True)
    for name in FILES:
        shutil.copyfile(os.path.join(OUT, name), os.path.join(dest, name))
    note = os.path.join(dest, 'masks', 'put-mask-sets-here.txt')
    if not os.path.exists(note):
        shutil.copyfile(os.path.join(OUT, 'masks', 'put-mask-sets-here.txt'), note)
    bad = [n for n in FILES if not filecmp.cmp(os.path.join(OUT, n), os.path.join(dest, n), shallow=False)]
    if bad:
        sys.exit('install check FAILED for: ' + ', '.join(bad))
    print('installed v%s -> %s (all %d files byte-identical; masks/ left alone)' % (VERSION, dest, len(FILES)))
    print('Close and reopen the plugin window in Designer to load it.')


def make_zip():
    path = os.path.join(HERE, 'dist', '%s-%s.zip' % (PLUGIN, VERSION))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, names in os.walk(OUT):
            dirs.sort()
            rel_root = os.path.relpath(root, os.path.dirname(OUT))
            z.writestr(rel_root.replace(os.sep, '/') + '/', '')
            for n in sorted(names):
                z.write(os.path.join(root, n), os.path.join(rel_root, n).replace(os.sep, '/'))
    print('zipped ->', path, '(%d KB)' % (os.path.getsize(path) // 1024))


if __name__ == '__main__':
    build()
    if len(sys.argv) == 3 and sys.argv[1] == '--install':
        install(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == '--zip':
        make_zip()
    elif len(sys.argv) > 1:
        sys.exit(__doc__)
