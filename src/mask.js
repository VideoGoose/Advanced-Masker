/*
 * Advanced Masker -- shared mask model and renderer (global AMask).
 *
 * Used by the plugin window (editor preview + PNG/TIF export) and by out.html (the page a
 * Designer Web layer loads), so what you see in the editor is what reaches the screens.
 *
 * Document:
 *   { v: 1, name, w, h, mapping (name the size came from), style: 0 luma (white keeps, black cuts) | 1 alpha (white, alpha = matte),
 *     invertAll: 0|1, masks: [Mask, ...] }          masks evaluate top (index 0) to bottom
 * Mask:
 *   { id, name, on, locked, closed, mode, inv, feather (px), fpos (where the feather sits:
 *     0 centred on the path, 1 inside it, 2 outside it), expand (px, signed), opacity (0-100), colour, pts: [Point, ...] }
 * Point (document pixels; handles are offsets from the point):
 *   { x, y, ix, iy, ox, oy, s }    s = 1 smooth (handles stay in line), 0 corner
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AMask = factory();
})(this, function () {
  'use strict';

  var MODES = ['add', 'subtract', 'intersect', 'lighten', 'darken', 'difference', 'none'];
  var MODE_LABELS = ['Add', 'Subtract', 'Intersect', 'Lighten', 'Darken', 'Difference', 'None'];
  var COLOURS = ['#f2b33d', '#3ec7f2', '#e5534b', '#3ecf6e', '#b67cf2', '#f27cc0', '#f2e93e', '#7cf2d9'];
  var MAX_SIZE = 16384, MAX_PX = 32000;
  var FPOS_LABELS = ['On the path', 'Inside', 'Outside'];

  function num(v, d, lo, hi) {
    v = Number(v);
    if (!isFinite(v)) v = d;
    if (lo !== undefined && v < lo) v = lo;
    if (hi !== undefined && v > hi) v = hi;
    return v;
  }
  function r2(v) { return Math.round(v * 100) / 100; }

  function defaults() {
    return { v: 1, name: 'Mask', w: 1920, h: 1080, mapping: '', style: 0, invertAll: 0, masks: [] };
  }

  var idSeq = 0;
  function newId() { idSeq++; return 'm' + Date.now().toString(36) + idSeq.toString(36); }

  function newMask(name, index) {
    return { id: newId(), name: name || 'Mask', on: 1, locked: 0, closed: 0, mode: 'add', inv: 0,
             feather: 0, fpos: 0, expand: 0, opacity: 100, colour: COLOURS[(index || 0) % COLOURS.length], pts: [] };
  }

  function point(x, y) { return { x: x, y: y, ix: 0, iy: 0, ox: 0, oy: 0, s: 0 }; }

  function sanitisePoint(p) {
    p = p || {};
    var lim = MAX_SIZE * 4;
    return { x: r2(num(p.x, 0, -lim, lim)), y: r2(num(p.y, 0, -lim, lim)),
             ix: r2(num(p.ix, 0, -lim, lim)), iy: r2(num(p.iy, 0, -lim, lim)),
             ox: r2(num(p.ox, 0, -lim, lim)), oy: r2(num(p.oy, 0, -lim, lim)), s: p.s ? 1 : 0 };
  }

  function sanitiseMask(m, i) {
    m = m || {};
    var out = newMask(String(m.name || 'Mask ' + (i + 1)).slice(0, 64), i);
    if (m.id && /^[A-Za-z0-9_-]{1,40}$/.test(m.id)) out.id = m.id;
    out.on = m.on === undefined ? 1 : (m.on ? 1 : 0);
    out.locked = m.locked ? 1 : 0;
    out.closed = m.closed ? 1 : 0;
    out.mode = MODES.indexOf(m.mode) >= 0 ? m.mode : 'add';
    out.inv = m.inv ? 1 : 0;
    out.feather = r2(num(m.feather, 0, 0, MAX_PX));
    out.fpos = m.fpos === 1 || m.fpos === 2 ? m.fpos : 0;
    out.expand = r2(num(m.expand, 0, -MAX_PX, MAX_PX));
    out.opacity = r2(num(m.opacity, 100, 0, 100));
    if (typeof m.colour === 'string' && /^#[0-9a-fA-F]{6}$/.test(m.colour)) out.colour = m.colour;
    out.pts = (Array.isArray(m.pts) ? m.pts : []).slice(0, 4096).map(sanitisePoint);
    return out;
  }

  function sanitise(d) {
    d = d || {};
    var out = defaults();
    out.name = String(d.name || out.name).slice(0, 80);
    out.mapping = String(d.mapping || '').slice(0, 120);
    out.w = Math.round(num(d.w, out.w, 1, MAX_SIZE));
    out.h = Math.round(num(d.h, out.h, 1, MAX_SIZE));
    out.style = d.style ? 1 : 0;
    out.invertAll = d.invertAll ? 1 : 0;
    out.masks = (Array.isArray(d.masks) ? d.masks : []).slice(0, 256).map(sanitiseMask);
    return out;
  }

  function clone(d) { return JSON.parse(JSON.stringify(d)); }

  // ---- compact text form for the Web layer URL ----------------------------
  // JSON with short keys, then base64url. Points are flat arrays: [x, y, ix, iy, ox, oy, s].
  function pack(d) {
    return { v: 1, n: d.name, w: d.w, h: d.h, mp: d.mapping, st: d.style, ia: d.invertAll,
             m: d.masks.map(function (m) {
               return { i: m.id, n: m.name, o: m.on, l: m.locked, c: m.closed, md: MODES.indexOf(m.mode), iv: m.inv,
                        f: m.feather, fp: m.fpos, e: m.expand, op: m.opacity, cl: m.colour,
                        p: [].concat.apply([], m.pts.map(function (p) { return [p.x, p.y, p.ix, p.iy, p.ox, p.oy, p.s]; })) };
             }) };
  }
  function unpack(o) {
    if (!o || typeof o !== 'object') return defaults();
    if (!o.m && o.masks) return sanitise(o);          // already the long form
    return sanitise({ name: o.n, w: o.w, h: o.h, mapping: o.mp, style: o.st, invertAll: o.ia,
      masks: (o.m || []).map(function (m) {
        var pts = [], p = Array.isArray(m.p) ? m.p : [];
        for (var k = 0; k + 6 < p.length; k += 7) pts.push({ x: p[k], y: p[k + 1], ix: p[k + 2], iy: p[k + 3], ox: p[k + 4], oy: p[k + 5], s: p[k + 6] });
        return { id: m.i, name: m.n, on: m.o, locked: m.l, closed: m.c, mode: MODES[m.md] || 'add', inv: m.iv,
                 feather: m.f, fpos: m.fp, expand: m.e, opacity: m.op, colour: m.cl, pts: pts };
      }) });
  }
  function b64urlEncode(str) {
    var bytes = new TextEncoder().encode(str), s = '', CH = 0x8000;
    for (var i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function b64urlDecode(s) {
    s = String(s || '').replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  }
  function encode(d) { return b64urlEncode(JSON.stringify(pack(d))); }
  function decode(s) {
    try { return unpack(JSON.parse(b64urlDecode(s))); } catch (e) { return null; }
  }

  // ---- bezier geometry ------------------------------------------------------
  // Segment i runs from pts[i] to pts[i+1] (or to pts[0] for the closing segment).
  function segCount(m) { return m.pts.length < 2 ? 0 : m.closed ? m.pts.length : m.pts.length - 1; }
  function segEnds(m, i) { return [m.pts[i], m.pts[(i + 1) % m.pts.length]]; }
  function bez(a, b, t) {
    var u = 1 - t, x1 = a.x + a.ox, y1 = a.y + a.oy, x2 = b.x + b.ix, y2 = b.y + b.iy;
    return { x: u * u * u * a.x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * b.x,
             y: u * u * u * a.y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * b.y };
  }
  // Split segment a->b at t without changing its shape: returns the new middle point and the
  // new out-handle of a and in-handle of b.
  function split(a, b, t) {
    function lerp(p, q) { return { x: p.x + (q.x - p.x) * t, y: p.y + (q.y - p.y) * t }; }
    var p0 = { x: a.x, y: a.y }, p1 = { x: a.x + a.ox, y: a.y + a.oy }, p2 = { x: b.x + b.ix, y: b.y + b.iy }, p3 = { x: b.x, y: b.y };
    var q0 = lerp(p0, p1), q1 = lerp(p1, p2), q2 = lerp(p2, p3), r0 = lerp(q0, q1), r1 = lerp(q1, q2), s = lerp(r0, r1);
    var straight = !a.ox && !a.oy && !b.ix && !b.iy;
    var mid = point(s.x, s.y);
    if (!straight) { mid.ix = r0.x - s.x; mid.iy = r0.y - s.y; mid.ox = r1.x - s.x; mid.oy = r1.y - s.y; mid.s = 1; }
    return { mid: mid, aOut: { x: q0.x - a.x, y: q0.y - a.y }, bIn: { x: q2.x - b.x, y: q2.y - b.y }, straight: straight };
  }
  // Nearest point on a segment to (x, y): coarse samples, then refine.
  function nearest(a, b, x, y) {
    var best = 0, bd = Infinity, N = 32;
    for (var i = 0; i <= N; i++) {
      var p = bez(a, b, i / N), d = (p.x - x) * (p.x - x) + (p.y - y) * (p.y - y);
      if (d < bd) { bd = d; best = i / N; }
    }
    var step = 1 / N;
    for (var k = 0; k < 12; k++) {
      step /= 2;
      [best - step, best + step].forEach(function (t) {
        if (t < 0 || t > 1) return;
        var p = bez(a, b, t), d = (p.x - x) * (p.x - x) + (p.y - y) * (p.y - y);
        if (d < bd) { bd = d; best = t; }
      });
    }
    return { t: best, d: Math.sqrt(bd) };
  }

  // Trace a mask path into ctx. tf(x, y) -> [X, Y] maps document pixels to ctx pixels.
  function trace(ctx, m, tf) {
    var n = m.pts.length;
    if (!n) return;
    var p0 = tf(m.pts[0].x, m.pts[0].y);
    ctx.moveTo(p0[0], p0[1]);
    for (var i = 0; i < segCount(m); i++) {
      var e = segEnds(m, i), a = e[0], b = e[1];
      var c1 = tf(a.x + a.ox, a.y + a.oy), c2 = tf(b.x + b.ix, b.y + b.iy), p = tf(b.x, b.y);
      if (!a.ox && !a.oy && !b.ix && !b.iy) ctx.lineTo(p[0], p[1]);
      else ctx.bezierCurveTo(c1[0], c1[1], c2[0], c2[1], p[0], p[1]);
    }
    if (m.closed) ctx.closePath();
  }

  function bounds(m) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    m.pts.forEach(function (p) {
      [[p.x, p.y], [p.x + p.ix, p.y + p.iy], [p.x + p.ox, p.y + p.oy]].forEach(function (q) {
        x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]);
      });
    });
    return { x0: x0, y0: y0, x1: x1, y1: y1 };
  }

  // ---- shapes ---------------------------------------------------------------
  function rectPts(x, y, w, h) {
    return [point(x, y), point(x + w, y), point(x + w, y + h), point(x, y + h)];
  }
  function ellipsePts(cx, cy, rx, ry) {
    var k = 0.5522847498;
    return [[0, -1], [1, 0], [0, 1], [-1, 0]].map(function (d) {
      var p = point(cx + d[0] * rx, cy + d[1] * ry);
      // tangent is perpendicular to the radius, clockwise
      p.ox = -d[1] * rx * k; p.oy = d[0] * ry * k; p.ix = -p.ox; p.iy = -p.oy; p.s = 1;
      return p;
    });
  }

  // ---- rendering ------------------------------------------------------------
  var blurOK = null;
  function canvasBlurWorks() {
    if (blurOK !== null) return blurOK;
    try {
      var c = mk(9, 9), x = c.getContext('2d');
      x.filter = 'blur(2px)';
      x.fillStyle = '#fff'; x.fillRect(4, 4, 1, 1);
      blurOK = x.getImageData(1, 4, 1, 1).data[3] > 0;
    } catch (e) { blurOK = false; }
    return blurOK;
  }
  function mk(w, h) {
    if (typeof OffscreenCanvas !== 'undefined') { try { return new OffscreenCanvas(w, h); } catch (e) {} }
    var c = document.createElement('canvas'); c.width = w; c.height = h; return c;
  }
  // Separable 3-pass box blur on a Float32 alpha plane (fallback when canvas filters don't work).
  function boxBlur(a, w, h, sigma) {
    var n = 3, wIdeal = Math.sqrt(12 * sigma * sigma / n + 1), wl = Math.floor(wIdeal);
    if (wl % 2 === 0) wl--;
    var m = Math.round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4));
    var tmp = new Float32Array(a.length);
    for (var pass = 0; pass < n; pass++) {
      var r = ((pass < m ? wl : wl + 2) - 1) / 2;
      if (r < 1) continue;
      pass1(a, tmp, w, h, r, 1, w); pass1(tmp, a, h, w, r, w, 1);
    }
    function pass1(src, dst, len, lines, rad, step, lineStep) {
      var iarr = 1 / (rad + rad + 1);
      for (var l = 0; l < lines; l++) {
        var base = l * lineStep, acc = 0, i;
        for (i = -rad; i <= rad; i++) acc += src[base + Math.min(len - 1, Math.max(0, i)) * step];
        for (i = 0; i < len; i++) {
          dst[base + i * step] = acc * iarr;
          acc += src[base + Math.min(len - 1, i + rad + 1) * step] - src[base + Math.max(0, i - rad) * step];
        }
      }
    }
  }

  // One mask's coverage (0..1) for an outW x outH image of the document rect `rect`.
  function coverage(m, outW, outH, rect, scratch) {
    var sx = outW / rect.w, sy = outH / rect.h, sc = (sx + sy) / 2;
    var sigma = m.feather > 0 ? m.feather * sc / 4 : 0;     // feather width = about 4 sigma, centred on the edge
    // Inside / Outside: move the edge half the feather width in / out first, so the soft band ends at the path
    var shift = m.fpos === 1 ? -m.feather / 2 : m.fpos === 2 ? m.feather / 2 : 0;
    var exp = (m.expand + shift) * sc;
    var pad = Math.ceil(sigma * 3 + 2);
    var W = outW + pad * 2, H = outH + pad * 2;
    var c = scratch.a && scratch.a.width === W && scratch.a.height === H ? scratch.a : (scratch.a = mk(W, H));
    var x = c.getContext('2d');
    x.setTransform(1, 0, 0, 1, 0, 0);
    x.globalCompositeOperation = 'source-over'; x.filter = 'none';
    x.clearRect(0, 0, W, H);
    function tf(px, py) { return [(px - rect.x) * sx + pad, (py - rect.y) * sy + pad]; }
    x.beginPath(); trace(x, m, tf);
    x.fillStyle = '#fff'; x.strokeStyle = '#fff'; x.lineJoin = 'round'; x.lineCap = 'round';
    x.fill('nonzero');
    if (exp > 0.01) { x.lineWidth = exp * 2; x.stroke(); }
    else if (exp < -0.01) { x.globalCompositeOperation = 'destination-out'; x.lineWidth = -exp * 2; x.stroke(); x.globalCompositeOperation = 'source-over'; }
    var src = c, useJs = false;
    if (sigma > 0.05) {
      if (canvasBlurWorks()) {
        var b = scratch.b && scratch.b.width === W && scratch.b.height === H ? scratch.b : (scratch.b = mk(W, H));
        var bx = b.getContext('2d');
        bx.setTransform(1, 0, 0, 1, 0, 0); bx.filter = 'none'; bx.clearRect(0, 0, W, H);
        bx.filter = 'blur(' + sigma.toFixed(3) + 'px)';
        bx.drawImage(c, 0, 0);
        bx.filter = 'none';
        src = b;
      } else useJs = true;
    }
    var out = new Float32Array(outW * outH), i;
    if (useJs) {
      var full = x.getImageData(0, 0, W, H).data, plane = new Float32Array(W * H);
      for (i = 0; i < plane.length; i++) plane[i] = full[i * 4 + 3] / 255;
      boxBlur(plane, W, H, sigma);
      for (var yy = 0; yy < outH; yy++) for (var xx = 0; xx < outW; xx++) out[yy * outW + xx] = plane[(yy + pad) * W + xx + pad];
    } else {
      var d = src.getContext('2d').getImageData(pad, pad, outW, outH).data;
      for (i = 0; i < out.length; i++) out[i] = d[i * 4 + 3] / 255;
    }
    return out;
  }

  function renderable(m) { return m.on && m.closed && m.pts.length >= 2 && m.mode !== 'none'; }

  // The final matte (Float32, 0..1) for an outW x outH image of document rect `rect`
  // (default: the whole document). Masks combine top to bottom; the first one starts from
  // empty for Add / Lighten / Difference and from full for Subtract / Intersect / Darken.
  // No renderable mask at all: everything shows (1).
  function matte(doc, outW, outH, rect) {
    rect = rect || { x: 0, y: 0, w: doc.w, h: doc.h };
    var n = outW * outH, acc = new Float32Array(n), i, scratch = {};
    var active = doc.masks.filter(renderable);
    var start = !active.length || ['subtract', 'intersect', 'darken'].indexOf(active[0].mode) >= 0 ? 1 : 0;
    if (start) acc.fill(1);
    active.forEach(function (m) {
      var c = coverage(m, outW, outH, rect, scratch), op = m.opacity / 100;
      for (i = 0; i < n; i++) {
        var v = c[i];
        if (m.inv) v = 1 - v;
        v *= op;
        var a = acc[i];
        switch (m.mode) {
          case 'add': a = a + v; if (a > 1) a = 1; break;
          case 'subtract': a = a - v; if (a < 0) a = 0; break;
          case 'intersect': a = a * v; break;
          case 'lighten': if (v > a) a = v; break;
          case 'darken': if (v < a) a = v; break;
          case 'difference': a = Math.abs(a - v); break;
        }
        acc[i] = a;
      }
    });
    if (doc.invertAll) for (i = 0; i < n; i++) acc[i] = 1 - acc[i];
    return acc;
  }

  // Draw the output picture into ctx (canvas sized outW x outH).
  // style 0 luma: opaque white where the mask keeps, black where it cuts.
  // style 1 alpha: white everywhere, alpha = matte.
  function render(ctx, doc, outW, outH, rect, styleOverride) {
    var a = matte(doc, outW, outH, rect), img = ctx.createImageData(outW, outH), d = img.data;
    var style = styleOverride === undefined ? doc.style : styleOverride;
    for (var i = 0; i < a.length; i++) {
      var v = Math.round(a[i] * 255), o = i * 4;
      if (style) { d[o] = d[o + 1] = d[o + 2] = 255; d[o + 3] = v; }
      else { d[o] = d[o + 1] = d[o + 2] = v; d[o + 3] = 255; }
    }
    ctx.putImageData(img, 0, 0);
    return a;
  }

  return { MODES: MODES, MODE_LABELS: MODE_LABELS, FPOS_LABELS: FPOS_LABELS, COLOURS: COLOURS, MAX_SIZE: MAX_SIZE,
           defaults: defaults, newMask: newMask, newId: newId, point: point, sanitise: sanitise, clone: clone,
           encode: encode, decode: decode, pack: pack, unpack: unpack,
           segCount: segCount, segEnds: segEnds, bez: bez, split: split, nearest: nearest, trace: trace,
           bounds: bounds, rectPts: rectPts, ellipsePts: ellipsePts, renderable: renderable,
           matte: matte, render: render, canvasBlurWorks: canvasBlurWorks };
});
