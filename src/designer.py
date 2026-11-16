# -*- coding: utf-8 -*-
"""
Advanced Masker -- Designer-side helper (Python 2.7, runs inside Designer).

The plugin window (served by Designer from this folder) calls these through Designer's own
/api/session/python/execute. Every call is one quick pass. Every function returns a JSON string.

    info(folder)                     project, plugin folder, export folders, capabilities
    web_layers()                     Web layers on the current track, with URL and mapping
    add_layer(name, seconds)         new Web layer at the playhead, Size mode -> Match Mapping
    make_bookmark(name, url)         WebBookmark holding the URL
    attach_bookmark(layer, path)     assign it to the layer
    set_url_field(layer, url)        fallback: a plain URL field
    set_url(layer, url)              live updates: rewrite the layer's URL
    set_mapping(layer, mapping)      assign a mapping (by name) to a layer
    mappings()                       project mappings with their pixel sizes
    write_export(folder, name, b64, first)   write a PNG/TIF into objects/<VideoFile|DxTexture>/masks/
    list_sets() / save_set(name, text) / delete_set(name)   mask set files in <plugin>/masks/
    list_images()                    still images under objects/DxTexture and objects/VideoFile
    read_image(rel, offset, size)    one base64 piece of such an image (reference picture)
    probe()                          dump member names to pin the soft spots

Designer's Python sandbox: no `import sys` / `traceback`, errors that are not Exception
subclasses (hence `except BaseException` + bare `except:`), never import inside a handler.
"""
try:
    from d3 import *  # noqa: F401,F403
except:  # noqa: E722
    pass

VERSION = '@VERSION@'
URL_FIELDS = ('url', 'URL', 'webUrl', 'address', 'link', 'page')
WEB_CLASS = 'WebModule'
BOOKMARK_CLASS = 'WebBookmark'
BOOKMARK_DIR = 'objects/webbookmark/'          # <prefix>/<lowercase type>/<name>.apx
BOOKMARK_FIELDS = ('bookmark', 'webBookmark', 'webbookmark', 'page', 'site')
BOOKMARK_URL_ATTRS = ('url', 'URL', 'address', 'link', 'webUrl', 'homeUrl', 'homepage')
MAPPING_FIELDS = ('mapping', 'Mapping', 'projection')
LAYER_SECONDS = 30
SIZE_MODE_FIELD = 'size_mode'
SIZE_MODE_MATCH_MAPPING = 0      # Designer's list: 0 Match Mapping, 1 Custom
PLUGIN_FOLDER = 'advanced-masker'      # plugins/<this>/
_FOLDER = [PLUGIN_FOLDER]              # the folder the window was served from (info(folder))
EXPORT_EXTS = ('.png', '.tif', '.tiff')
EXPORT_FOLDERS = ('VideoFile', 'DxTexture')     # objects/<one of these>/masks/
EXPORT_SUB = 'masks'
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
IMAGE_MAX = 64 * 1024 * 1024
SET_DIR = 'masks'
SET_MAX = 4 * 1024 * 1024
# Designer's mapping classes (seen in its own editors). allResources on the base class may
# or may not include subclasses, so each is asked in turn and the results de-duplicated.
MAPPING_CLASSES = ('Projection', 'DirectProjection', 'FeedProjection', 'DynamicFeedProjection',
                   'PerspectiveProjection', 'ParallelProjection', 'CylindricalProjection',
                   'SphericalProjection', 'FisheyeProjection', 'MeshProjection', 'MultiProjection',
                   'RadialProjection', 'CameraPlateProjection', 'SpatialProjection', 'FlatMapProjection')
RES_ATTRS = ('resolution', 'canvasResolution', 'outputResolution', 'canvasSize', 'pixelResolution',
             'textureResolution', 'res', 'size')
SCREEN_RES_ATTRS = ('resolution', 'canvasResolution', 'pixelResolution', 'res')
SCREEN_LIST_ATTRS = ('screens', 'screenList', 'targets', 'displays', 'surfaces')

try:
    unicode
except NameError:          # lets the test-suite run this under Python 3
    unicode = str
    basestring = str
    long = int


# ------------------------------------------------------------------ JSON
def _esc(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif o < 0x20 or o > 0x7e:
            out.append('\\u%04x' % o if o < 0x10000 else '?')
        else:
            out.append(ch)
    return ''.join(out)


def _dumps(v):
    if v is None:
        return 'null'
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if isinstance(v, (int, long)):
        return '%d' % v          # not repr(): a Python 2 long prints as 123L (file sizes on Windows)
    if isinstance(v, float):
        return repr(v) if v == v and v not in (float('inf'), float('-inf')) else 'null'
    if isinstance(v, basestring):
        if isinstance(v, str) and not isinstance(v, unicode):
            try:
                v = v.decode('utf-8')
            except:  # noqa: E722
                v = v.decode('latin-1')
        return '"' + _esc(v) + '"'
    if isinstance(v, dict):
        return '{' + ','.join(_dumps(unicode(k)) + ':' + _dumps(x) for k, x in v.items()) + '}'
    if isinstance(v, (list, tuple)):
        return '[' + ','.join(_dumps(x) for x in v) + ']'
    return _dumps(unicode(repr(v)))


def _ok(**kw):
    kw['ok'] = True
    return _dumps(kw)


def _fail(e, **kw):
    kw['ok'] = False
    kw['error'] = unicode(e)
    return _dumps(kw)


# ----------------------------------------------------------------- utils
def _get(obj, names):
    for n in names:
        try:
            v = getattr(obj, n)
        except:  # noqa: E722
            continue
        if v is not None:
            return n, v
    return None, None


def _name(obj):
    for n in ('description', 'name'):
        try:
            v = getattr(obj, n)
            if v:
                return unicode(v)
        except:  # noqa: E722
            pass
    return unicode(repr(obj))


def _lname(layer):
    try:
        n = layer.name
        if n:
            return unicode(n)
    except:  # noqa: E722
        pass
    return _name(layer)


def _xy(v):
    if callable(v):
        try:
            v = v()
        except:  # noqa: E722
            return 0, 0
    for a, b in (('x', 'y'), ('width', 'height'), ('w', 'h')):
        try:
            return int(round(float(getattr(v, a)))), int(round(float(getattr(v, b))))
        except:  # noqa: E722
            pass
    try:
        return int(round(float(v[0]))), int(round(float(v[1])))
    except:  # noqa: E722
        return 0, 0


def _gs():
    try:
        return guisystem  # noqa: F821
    except NameError:
        return None


def _now():
    gs = _gs()
    for p in (('player', 'tCurrent'), ('track', 'player', 'tCurrent'), ('tCurrent',)):
        o = gs
        try:
            for a in p:
                o = getattr(o, a)
            return float(o)
        except:  # noqa: E722
            continue
    return 0.0


def _os():
    try:
        import os
        return os
    except:  # noqa: E722
        return None


def _b64decode(s):
    try:
        import base64
        return base64.b64decode(s)
    except:  # noqa: E722
        pass
    try:
        import binascii
        return binascii.a2b_base64(s)
    except:  # noqa: E722
        pass
    return s.decode('base64')    # Py2 built-in codec, no import needed


def _b64encode(data):
    try:
        import base64
        out = base64.b64encode(data)
    except:  # noqa: E722
        try:
            import binascii
            out = binascii.b2a_base64(data).replace(b'\n', b'')
        except:  # noqa: E722
            out = data.encode('base64').replace('\n', '')
    if not isinstance(out, unicode):
        out = out.decode('ascii')
    return out


def _public(o):
    try:
        return sorted(a for a in dir(o) if not a.startswith('_'))
    except:  # noqa: E722
        return []


# ------------------------------------------------------------ track/layers
def _track():
    gs = _gs()
    return getattr(gs, 'track', None) if gs else None


def _layers():
    t = _track()
    try:
        return list(t.layers)
    except:  # noqa: E722
        return []


def _cls(name):
    """Class from the d3 names this module received. Never imports: Designer's
    restricted scope blocks `import d3` / `import sys` at run time."""
    c = globals().get(name)
    if c is None:
        try:
            c = __builtins__.get(name) if isinstance(__builtins__, dict) else getattr(__builtins__, name, None)
        except:  # noqa: E722
            c = None
    return c


def _names_like(*words):
    out = []
    for k in list(globals().keys()):
        lk = k.lower()
        if any(w in lk for w in words) and not k.startswith('_') and k != k.upper():
            out.append(k)
    return sorted(out)


def _is_web(layer):
    mt = getattr(layer, 'moduleType', None)
    if mt is None:
        return False
    if mt is _cls(WEB_CLASS):
        return True
    return WEB_CLASS in getattr(mt, '__name__', unicode(mt))


def _field_name(fs):
    _, n = _get(fs, ('name', 'fieldName', 'description', 'displayName', 'userName'))
    return unicode(n) if n is not None else u''


def _fields(layer):
    return [_field_name(f) for f in getattr(layer, 'fields', [])]


def _find_field(layer, names, contains=None):
    for n in names:
        try:
            fs = layer.findSequence(n)
        except:  # noqa: E722
            fs = None
        if fs is not None:
            return n, fs
    try:
        fields = list(layer.fields)
    except:  # noqa: E722
        return None, None
    low = [u.lower() for u in names]
    for f in fields:
        fn = _field_name(f)
        if fn.lower() in low or (contains and contains in fn.lower()):
            return fn, f
    return None, None


def _url_field(layer):
    return _find_field(layer, URL_FIELDS)


def _bookmark_field(layer):
    return _find_field(layer, BOOKMARK_FIELDS, 'bookmark')


def _mapping_field(layer):
    return _find_field(layer, MAPPING_FIELDS)


def _seq(fs):
    return getattr(fs, 'sequence', fs)


def _t0(layer):
    try:
        return float(layer.tStart)
    except:  # noqa: E722
        return _now()


def _read(fs, t):
    try:
        v = fs.eval(t, u'')
        if v is not None:
            return unicode(v)
    except:  # noqa: E722
        pass
    seq = _seq(fs)
    for how in ('getString', 'getValue', 'get'):
        fn = getattr(seq, how, None)
        if fn is None:
            continue
        try:
            v = fn(t)
            if v is not None:
                return unicode(v)
        except:  # noqa: E722
            continue
    try:
        return unicode(seq.key(0).v)
    except:  # noqa: E722
        return None


def _write(fs, value, t):
    """Constant text value: sequencing off, one key at the layer's start beat."""
    try:
        fs.disableSequencing = True
    except:  # noqa: E722
        pass
    seq = _seq(fs)
    try:
        seq.setString(t, value)
        return 'setString'
    except:  # noqa: E722
        pass
    try:
        seq.key(0).v = value
        return 'key(0).v'
    except:  # noqa: E722
        pass
    for how in ('setValue', 'set'):
        fn = getattr(seq, how, None)
        if fn is None:
            continue
        try:
            fn(t, value)
            return how
        except:  # noqa: E722
            continue
    return None


def _find(name):
    for l in _layers():
        if _lname(l) == name:
            return l
    return None


def _notify(layer, fs):
    try:
        layer.notifyEdit(fs)
    except:  # noqa: E722
        pass


def _span(track, start, seconds):
    try:
        return track.timeToBeat(track.beatToTime(start) + seconds) - start
    except:  # noqa: E722
        return seconds


def _rm():
    try:
        return resourceManager  # noqa: F821
    except NameError:
        return None


def _safe_name(name, fallback=u'mask'):
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch in u' _-.') else u'_')
    s = u''.join(out).strip().strip(u'.')
    return (s or fallback)[:80]


def _resource_value(fs, t):
    """A resource held by a field (bookmark, mapping), without evaluating expressions."""
    try:
        r = fs.eval(t, None)
        if r is not None and not isinstance(r, (basestring, int, long, float)):
            return r
    except:  # noqa: E722
        pass
    try:
        k = _seq(fs).key(0)
        for a in ('r', 'v', 'resource'):
            r = getattr(k, a, None)
            if r is not None and not isinstance(r, (basestring, int, long, float)):
                return r
    except:  # noqa: E722
        pass
    return None


def _assign_resource(fs, res, t):
    try:
        fs.disableSequencing = True
    except:  # noqa: E722
        pass
    seq = _seq(fs)
    try:
        seq.setResource(t, res)
        return 'setResource'
    except:  # noqa: E722
        pass
    try:
        seq.key(0).r = res
        return 'key(0).r'
    except:  # noqa: E722
        pass
    try:
        seq.key(0).v = res
        return 'key(0).v'
    except:  # noqa: E722
        return None


# ------------------------------------------------------------- bookmarks
def _bm_url_attr(bm):
    for a in BOOKMARK_URL_ATTRS:
        try:
            v = getattr(bm, a)
        except:  # noqa: E722
            continue
        if isinstance(v, basestring) or v is None:
            return a
    return None


def _bm_set_url(bm, url):
    a = _bm_url_attr(bm)
    if a is None:
        return None
    setattr(bm, a, url)
    for save in ('saveOnDelete', 'save'):
        try:
            getattr(bm, save)()
            break
        except:  # noqa: E722
            continue
    return a


def _bm_get_url(bm):
    a = _bm_url_attr(bm)
    try:
        return unicode(getattr(bm, a)) if a else None
    except:  # noqa: E722
        return None


class _NoClass(Exception):
    pass


def _make_bookmark(name, url):
    _at(u'find resourceManager')
    rm = _rm()
    cls = _cls(BOOKMARK_CLASS)
    if rm is None:
        raise _NoClass('resourceManager not available')
    if cls is None:
        raise _NoClass('%s class not available to plugins (similar names: %s)'
                       % (BOOKMARK_CLASS, ', '.join(_names_like('bookmark', 'web')) or 'none'))
    path = BOOKMARK_DIR + _safe_name(name).lower() + '.apx'
    _at(u'loadOrCreate ' + path)
    bm = rm.loadOrCreate(path, cls)
    if bm is None:
        raise Exception('loadOrCreate returned nothing for ' + path)
    _at(u'set bookmark URL')
    how = _bm_set_url(bm, url)
    return bm, path, how


def _layer_bookmark(layer):
    fn, fs = _bookmark_field(layer)
    return _resource_value(fs, _t0(layer)) if fs is not None else None


# ----------------------------------------------------------------- guard
_STEP = [u'']


def _at(step):
    """Record the sub-step in progress so an error can say where it happened."""
    _STEP[0] = step


def _guard(fn, *a):
    """Run fn; whatever is raised, answer with JSON."""
    _at(u'')
    try:
        return fn(*a)
    except BaseException as e:
        try:
            msg = u'%s: %s' % (type(e).__name__, e)
        except:  # noqa: E722
            msg = u'unprintable error'
        return _dumps({'ok': False, 'error': msg, 'step': _STEP[0]})
    except:  # noqa: E722  (old-style class raised)
        return _dumps({'ok': False, 'error': u'non-standard error', 'step': _STEP[0]})


# -------------------------------------------------------------- mappings
def _mapping_objects():
    rm = _rm()
    if rm is None:
        return []
    seen, out = set(), []
    for cname in MAPPING_CLASSES:
        cls = _cls(cname)
        if cls is None:
            continue
        try:
            found = list(rm.allResources(cls))
        except:  # noqa: E722
            continue
        for m in found:
            if id(m) in seen:
                continue
            seen.add(id(m))
            out.append(m)
    return out


def _screen_list(m):
    for a in SCREEN_LIST_ATTRS:
        try:
            v = getattr(m, a)
        except:  # noqa: E722
            continue
        if v is None or isinstance(v, basestring):
            continue
        try:
            items = list(v)
        except:  # noqa: E722
            continue
        if items:
            return a, items
    return None, []


def _screen_size(s):
    _, res = _get(s, SCREEN_RES_ATTRS)
    return _xy(res) if res is not None else (0, 0)


def _mapping_info(m):
    """Name, type and pixel size of a mapping. Size: the mapping's own resolution if it has
    one, else its single screen's, else the bounding size of its screens side by side."""
    info = {'name': _name(m), 'type': type(m).__name__, 'w': 0, 'h': 0, 'via': None, 'screens': []}
    for a in RES_ATTRS:
        try:
            v = getattr(m, a)
        except:  # noqa: E722
            continue
        if v is None or isinstance(v, basestring):
            continue
        w, h = _xy(v)
        if w > 0 and h > 0:
            info.update(w=w, h=h, via=a)
            break
    sa, screens = _screen_list(m)
    for s in screens[:64]:
        w, h = _screen_size(s)
        info['screens'].append({'name': _name(s), 'w': w, 'h': h})
    if not info['w'] and info['screens']:
        sized = [s for s in info['screens'] if s['w'] > 0 and s['h'] > 0]
        if len(sized) == 1:
            info.update(w=sized[0]['w'], h=sized[0]['h'], via=sa + '[0].resolution')
        elif sized:
            info.update(w=max(s['w'] for s in sized), h=max(s['h'] for s in sized), via=sa + ' (largest)')
    return info


def _mappings_impl():
    out = [_mapping_info(m) for m in _mapping_objects()]
    out.sort(key=lambda x: x['name'].lower())
    return _ok(mappings=out, classes=[c for c in MAPPING_CLASSES if _cls(c) is not None])


def _mapping_by_name(name):
    for m in _mapping_objects():
        if _name(m) == name:
            return m
    return None


def _set_mapping_step(layer_name, mapping_name):
    _at(u'find layer')
    layer = _find(layer_name)
    if layer is None:
        return _fail('no layer named %s on this track' % layer_name)
    _at(u'find mapping')
    m = _mapping_by_name(mapping_name)
    if m is None:
        return _fail('no mapping named %s' % mapping_name)
    fn, fs = _mapping_field(layer)
    if fs is None:
        return _fail('layer has no mapping field', fields=_fields(layer))
    _at(u'assign mapping')
    how = _assign_resource(fs, m, _t0(layer))
    if not how:
        return _fail('could not assign the mapping', field=fn)
    _notify(layer, fs)
    return _ok(layer=layer_name, mapping=mapping_name, field=fn, how=how)


# --------------------------------------------- stepwise layer + bookmark
def _key0(fs):
    try:
        v = _seq(fs).key(0).v
        return int(v) if isinstance(v, (int, long, float)) else unicode(v)
    except:  # noqa: E722
        return None


def _set_enum(layer, field, value):
    """Constant value on an enum field (sequencing off). Never fs.eval() size_mode: Designer
    resolves it against the layer's mapping and evaluating it from Python hits a recursion limit."""
    try:
        fs = layer.findSequence(field)
    except:  # noqa: E722
        fs = None
    if fs is None:
        return None, None, None
    t = _t0(layer)
    before = _key0(fs)
    try:
        fs.disableSequencing = True
    except:  # noqa: E722
        pass
    seq = _seq(fs)
    for how, fn in (('setFloat', lambda: seq.setFloat(t, float(value))),
                    ('key(0).v', lambda: setattr(seq.key(0), 'v', value)),
                    ('setValue', lambda: seq.setValue(t, value))):
        try:
            fn()
            _notify(layer, fs)
            return before, how, _key0(fs)
        except:  # noqa: E722
            continue
    return before, None, _key0(fs)


def _add_layer(name, seconds):
    track = _track()
    if track is None:
        return _fail('guisystem.track not available')
    cls = _cls(WEB_CLASS)
    if cls is None:
        return _fail('%s class not found in d3' % WEB_CLASS)
    existing = set(_lname(l) for l in _layers())
    base, n = name, 2
    while name in existing:
        name = u'%s %d' % (base, n)
        n += 1
    start = _now()
    layer = track.addNewLayer(cls, start, _span(track, start, seconds), name)
    if layer is None:
        layer = _find(name)
    if layer is None:
        return _fail('addNewLayer returned nothing and no layer named %s' % name)
    bf, _ = _bookmark_field(layer)
    _at(u'set size mode')
    before, how, after = _set_enum(layer, SIZE_MODE_FIELD, SIZE_MODE_MATCH_MAPPING)
    return _ok(layer=_lname(layer), seconds=seconds, fields=_fields(layer), bookmarkField=bf,
               sizeModeBefore=before, sizeModeAfter=after, sizeModeHow=how)


def _make_bookmark_step(name, url):
    bm, path, how = _make_bookmark(name, url)
    if not how:
        return _fail('bookmark created but it has no URL property I recognise',
                     bookmark=_name(bm), path=path, attrs=_public(bm))
    return _ok(bookmark=_name(bm), path=path, urlAttr=how)


def _attach_step(layer_name, path):
    _at(u'find layer')
    layer = _find(layer_name)
    if layer is None:
        return _fail('no layer named %s on this track' % layer_name)
    rm, cls = _rm(), _cls(BOOKMARK_CLASS)
    _at(u'load bookmark ' + path)
    bm = rm.loadOrCreate(path, cls)
    _at(u'find bookmark field')
    bf, bfs = _bookmark_field(layer)
    if bfs is None:
        return _fail('layer has no bookmark field I recognise', fields=_fields(layer))
    _at(u'assign bookmark to ' + bf)
    how = _assign_resource(bfs, bm, _t0(layer))
    if not how:
        return _fail('could not assign the bookmark', field=bf)
    _notify(layer, bfs)
    return _ok(layer=layer_name, field=bf, how=how)


def _url_field_step(layer_name, url):
    layer = _find(layer_name)
    if layer is None:
        return _fail('no layer named %s on this track' % layer_name)
    fn, fs = _url_field(layer)
    if fs is None:
        return _fail('no URL field', fields=_fields(layer))
    how = _write(fs, url, _t0(layer))
    if not how:
        return _fail('could not write the URL field', field=fn)
    _notify(layer, fs)
    return _ok(field=fn, how=how)


def _web_layers_impl():
    out = []
    for l in _layers():
        if not _is_web(l):
            continue
        bm = _layer_bookmark(l)
        url, via = None, None
        if bm is not None:
            url, via = _bm_get_url(bm), 'bookmark ' + _name(bm)
        else:
            fn, fs = _url_field(l)
            if fs is not None:
                url, via = _read(fs, _t0(l)), 'field ' + fn
        mapping = None
        try:
            mf, mfs = _mapping_field(l)
            mres = _resource_value(mfs, _t0(l)) if mfs is not None else None
            if mres is not None:
                mapping = _mapping_info(mres)
        except BaseException:
            mapping = None
        out.append({'name': _lname(l), 'url': url, 'via': via, 'mapping': mapping})
    return _ok(layers=out)


def _set_url_impl(layer_name, url):
    layer = _find(layer_name)
    if layer is None:
        return _fail('no layer named %s on this track' % layer_name)
    bm = _layer_bookmark(layer)
    if bm is not None:
        how = _bm_set_url(bm, url)
        if not how:
            return _fail('bookmark has no URL property', bookmark=_name(bm), attrs=_public(bm))
        return _ok(layer=layer_name, bookmark=_name(bm), how='bookmark.' + how)
    fn, fs = _url_field(layer)
    if fs is None:
        return _fail('layer has no bookmark assigned and no URL field', fields=_fields(layer))
    how = _write(fs, url, _t0(layer))
    if not how:
        return _fail('could not write the URL field', field=fn)
    _notify(layer, fs)
    return _ok(layer=layer_name, field=fn, how=how)


# ---------------------------------------------------------- folders, files
def _module_names():
    out = []
    for f in (_FOLDER[0], PLUGIN_FOLDER):
        for n in (f, f.replace('-', '_'), 'user_module_' + f, 'user_module_' + f.replace('-', '_')):
            if n not in out:
                out.append(n)
    return out


def _plugin_dir():
    os = _os()
    if os is None:
        return None
    found = None
    for mod in _module_names():
        try:
            m = __import__(mod)
            f = getattr(m, '__file__', None)
            if f:
                found = os.path.dirname(os.path.abspath(f))
                break
        except:  # noqa: E722
            continue
    if found is None:
        f = globals().get('__file__')
        found = os.path.dirname(os.path.abspath(f)) if f else None
    if found is None:
        return None
    want = os.path.join(os.path.dirname(found), _FOLDER[0])
    if os.path.basename(found) != _FOLDER[0] and os.path.isdir(want):
        return want
    return found


def _project_dir():
    os = _os()
    pd = _plugin_dir()
    if os and pd and os.path.basename(os.path.dirname(pd)).lower() == 'plugins':
        return os.path.dirname(os.path.dirname(pd))
    return None


def _objects_child(os, proj, name):
    """objects/<name> using the spelling already on disk (VideoFile / videofile)."""
    od = os.path.join(proj, 'objects')
    try:
        for f in os.listdir(od):
            if f.lower() == name.lower() and os.path.isdir(os.path.join(od, f)):
                return os.path.join(od, f)
    except:  # noqa: E722
        pass
    return os.path.join(od, name)


def _export_dir(folder):
    os = _os()
    proj = _project_dir()
    if not (os and proj):
        raise Exception('project folder not found from Designer Python')
    names = [f for f in EXPORT_FOLDERS if f.lower() == unicode(folder).lower()]
    if not names:
        raise Exception('export folder must be one of ' + ', '.join(EXPORT_FOLDERS))
    return os, os.path.join(_objects_child(os, proj, names[0]), EXPORT_SUB)


def _info():
    os = _os()
    caps = {'os': os is not None}
    for mod in ('base64', 'binascii'):
        try:
            __import__(mod)
            caps[mod] = True
        except:  # noqa: E722
            caps[mod] = False
    proj = _project_dir()
    dirs = {}
    if os and proj:
        for f in EXPORT_FOLDERS:
            dirs[f] = os.path.join(_objects_child(os, proj, f), EXPORT_SUB)
    return {'ok': True, 'version': VERSION, 'project': proj, 'pluginDir': _plugin_dir(),
            'exportDirs': dirs, 'caps': caps, 'now': _now()}


def _info_impl(folder=None):
    if folder and folder not in (u'.', u'..') and '/' not in folder and chr(92) not in folder:
        _FOLDER[0] = unicode(folder)
    return _dumps(_info())


def _write_export_impl(folder, name, b64, first):
    os, d = _export_dir(folder)
    fname = _safe_name(name)
    if not fname.lower().endswith(EXPORT_EXTS):
        raise Exception('only .png / .tif files can be written')
    if not os.path.isdir(d):
        os.makedirs(d)
    p = os.path.join(d, fname)
    data = _b64decode(b64)
    f = open(p, 'wb' if first else 'ab')
    try:
        f.write(data)
    finally:
        f.close()
    return _ok(path=p, size=os.path.getsize(p))


def _read_text(p):
    f = open(p, 'rb')
    try:
        data = f.read()
    finally:
        f.close()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return data.decode(enc)
        except:  # noqa: E722
            continue
    return u''


def _write_text(p, text):
    if not isinstance(text, unicode):
        text = text.decode('utf-8')
    f = open(p, 'wb')
    try:
        f.write(text.encode('utf-8'))
    finally:
        f.close()


def _need_plugin_dir():
    os, pd = _os(), _plugin_dir()
    if not (os and pd):
        raise Exception('plugin folder not found from Designer Python')
    return os, pd


def _set_file(name):
    os, pd = _need_plugin_dir()
    safe = _safe_name(name)
    if safe.startswith(u'.'):
        safe = u'_' + safe[1:]
    return os, os.path.join(pd, SET_DIR), safe + u'.json'


def _list_sets_impl():
    _at(u'find plugin folder')
    os, pd = _need_plugin_dir()
    d = os.path.join(pd, SET_DIR)
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if not f.lower().endswith('.json') or not os.path.isfile(p) or os.path.getsize(p) > SET_MAX:
                continue
            _at(u'read ' + f)
            out.append({'file': f, 'text': _read_text(p)})
    return _ok(sets=out, dir=d)


def _save_set_impl(name, text):
    if not text or len(text) > SET_MAX or not text.lstrip().startswith(u'{'):
        return _fail('mask set must be a JSON object under %d KB' % (SET_MAX // 1024))
    os, d, f = _set_file(name)
    if not os.path.isdir(d):
        os.makedirs(d)
    p = os.path.join(d, f)
    _at(u'write ' + p)
    _write_text(p, text)
    return _ok(file=f, path=p, dir=d)


def _delete_set_impl(name):
    os, d, f = _set_file(name)
    p = os.path.join(d, f)
    if not os.path.isfile(p):
        return _fail('no mask set file %s' % f)
    os.remove(p)
    return _ok(file=f, path=p)


def _list_images_impl():
    os = _os()
    proj = _project_dir()
    if not (os and proj):
        return _ok(images=[], note='project folder not found')
    out = []
    od = os.path.join(proj, 'objects')
    for sub in ('DxTexture', 'VideoFile'):
        root = _objects_child(os, proj, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs.sort()
            for f in sorted(files):
                if not f.lower().endswith(IMAGE_EXTS):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(p)
                except:  # noqa: E722
                    continue
                if size > IMAGE_MAX:
                    continue
                out.append({'rel': os.path.relpath(p, od).replace(chr(92), '/'), 'size': size})
                if len(out) >= 500:
                    return _ok(images=out, more=True)
    return _ok(images=out)


def _read_image_impl(rel, offset, size):
    os = _os()
    proj = _project_dir()
    if not (os and proj):
        raise Exception('project folder not found')
    rel = unicode(rel).replace(chr(92), '/')
    parts = rel.split('/')
    if '..' in parts or rel.startswith('/') or ':' in rel or not rel.lower().endswith(IMAGE_EXTS):
        raise Exception('not an image path under objects/')
    p = os.path.join(proj, 'objects', *parts)
    if not os.path.isfile(p):
        raise Exception('no file ' + rel)
    total = os.path.getsize(p)
    f = open(p, 'rb')
    try:
        f.seek(int(offset))
        data = f.read(max(1, min(int(size), 1024 * 1024)))
    finally:
        f.close()
    return _ok(b64=_b64encode(data), total=total, offset=int(offset), n=len(data))


def _probe_impl():
    out = {'info': _info()}
    out['mappingClasses'] = dict((c, _cls(c) is not None) for c in MAPPING_CLASSES)
    out['namesLikeProjection'] = _names_like('projection', 'mapping')
    maps = []
    for m in _mapping_objects()[:6]:
        try:
            maps.append({'info': _mapping_info(m), 'attrs': _public(m)})
        except BaseException as e:
            maps.append({'error': unicode(e)})
    out['mappings'] = maps or 'none found'
    webs = []
    for l in _layers():
        if not _is_web(l):
            continue
        try:
            mf, mfs = _mapping_field(l)
            webs.append({'layer': _lname(l), 'fields': _fields(l), 'mappingField': mf,
                         'mappingFieldType': type(mfs).__name__ if mfs is not None else None})
        except BaseException as e:
            webs.append({'layer': _lname(l), 'error': unicode(e)})
    out['webLayers'] = webs or 'none on this track'
    return _dumps(out)


# ------------------------------------------------- guarded public entry points
def info(folder=None):
    return _guard(_info_impl, folder)


def web_layers():
    return _guard(_web_layers_impl)


def add_layer(name, seconds=LAYER_SECONDS):
    return _guard(_add_layer, name, seconds)


def make_bookmark(name, url):
    return _guard(_make_bookmark_step, name, url)


def attach_bookmark(layer_name, path):
    return _guard(_attach_step, layer_name, path)


def set_url_field(layer_name, url):
    return _guard(_url_field_step, layer_name, url)


def set_url(layer_name, url):
    return _guard(_set_url_impl, layer_name, url)


def set_mapping(layer_name, mapping_name):
    return _guard(_set_mapping_step, layer_name, mapping_name)


def mappings():
    return _guard(_mappings_impl)


def write_export(folder, name, b64, first):
    return _guard(_write_export_impl, folder, name, b64, first)


def list_sets():
    return _guard(_list_sets_impl)


def save_set(name, text):
    return _guard(_save_set_impl, name, text)


def delete_set(name):
    return _guard(_delete_set_impl, name)


def list_images():
    return _guard(_list_images_impl)


def read_image(rel, offset, size):
    return _guard(_read_image_impl, rel, offset, size)


def probe():
    return _guard(_probe_impl)
