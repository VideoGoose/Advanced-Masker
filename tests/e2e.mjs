// End-to-end against mock_designer.py with headless Chromium.
// node tests/e2e.mjs <port> <outdir> <projectdir>   (mock_designer.py must be running on <port>)
import { chromium } from "playwright";
import fs from "fs";
import path from "path";
const [port, out, proj] = process.argv.slice(2);
const base = `http://127.0.0.1:${port}`;
const world = async () => (await fetch(base + "/__world")).json();
const res = {}, errs = [];
const check = (name, ok, extra) => { res[name] = ok ? "ok" : "FAIL " + JSON.stringify(extra ?? ""); if (!ok) errs.push(name); };

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ acceptDownloads: true });
const ui = await ctx.newPage();
ui.on("pageerror", (e) => errs.push("ui: " + e.message));
ui.on("dialog", (d) => { errs.push("browser dialog used: " + d.message()); d.dismiss(); });
await ui.setViewportSize({ width: 1400, height: 900 });
await ui.goto(base + "/plugins/advanced-masker/index.html");
await ui.evaluate(() => localStorage.clear());
await ui.reload();
await ui.waitForFunction(() => /connected/.test(document.getElementById("statusTxt").textContent), null, { timeout: 8000 });

// doc point -> page point on the editor canvas
async function at(x, y) {
  return ui.evaluate(([x, y]) => {
    const r = document.getElementById("view").getBoundingClientRect(), v = window.__am.view;
    return [r.left + v.x + x * v.z, r.top + v.y + y * v.z];
  }, [x, y]);
}
async function click(x, y) { const p = await at(x, y); await ui.mouse.click(p[0], p[1]); await ui.waitForTimeout(30); }
async function dragDoc(x0, y0, x1, y1, mods) {
  const a = await at(x0, y0), b = await at(x1, y1);
  for (const m of mods || []) await ui.keyboard.down(m);
  await ui.mouse.move(a[0], a[1]); await ui.mouse.down();
  await ui.mouse.move((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, { steps: 3 }); await ui.mouse.move(b[0], b[1], { steps: 3 });
  await ui.mouse.up();
  for (const m of mods || []) await ui.keyboard.up(m);
  await ui.waitForTimeout(30);
}
const D = () => ui.evaluate(() => JSON.parse(JSON.stringify(window.__am.doc)));
// matte value at doc points, rendered small through the shared renderer
const matteAt = (pts) => ui.evaluate((pts) => {
  const d = window.__am.doc, k = 0.25, w = Math.round(d.w * k), h = Math.round(d.h * k), a = AMask.matte(d, w, h);
  return pts.map((p) => +a[Math.round(p[1] * k) * w + Math.round(p[0] * k)].toFixed(3));
}, pts);
async function pickPopup(btnSel, text) {
  await ui.click(btnSel);
  await ui.waitForSelector(".pick-list");
  await ui.locator(".pick-list div", { hasText: text }).first().click();
  await ui.waitForTimeout(100);
}

// 1. size from a mapping (FeedProjection with its own resolution)
await pickPopup("#sizeFrom", "feed stage");
let d = await D();
check("sizeFromMapping", d.w === 2560 && d.h === 1440 && d.mapping === "feed stage", [d.w, d.h, d.mapping]);
// DirectProjection: size from its screen
await ui.click("#sizeFrom"); await ui.waitForSelector(".pick-list");
res.mappingList = await ui.evaluate(() => [...document.querySelectorAll(".pick-list div")].map((x) => x.textContent));
await ui.mouse.click(5, 5);
check("directMappingSize", res.mappingList.some((t) => /direct LED_A.*1152 × 576/.test(t)), res.mappingList);

// 2. pen: 4 points (one curve), close on the first point
await ui.click('#tools button[data-tool="pen"]');
await click(600, 300);
await dragDoc(1600, 300, 1800, 300);          // smooth point with handles
await click(1600, 1100);
await click(600, 1100);
await click(600, 300);                         // close
d = await D();
check("penClosed", d.masks.length === 1 && d.masks[0].closed === 1 && d.masks[0].pts.length === 4, d.masks.map((m) => [m.closed, m.pts.length]));
check("smoothHandles", d.masks[0].pts[1].s === 1 && Math.abs(d.masks[0].pts[1].ox - 200) < 3 && Math.abs(d.masks[0].pts[1].ix + 200) < 3, d.masks[0].pts[1]);
let mv = await matteAt([[1100, 700], [200, 200], [2400, 1300]]);
check("matteInsideOutside", mv[0] === 1 && mv[1] === 0 && mv[2] === 0, mv);

// 3. rectangle tool + Subtract makes a hole; the eye turns it off again
await ui.click('#tools button[data-tool="rect"]');
await dragDoc(900, 550, 1300, 850);
d = await D();
check("rectMask", d.masks.length === 2 && d.masks[1].pts.length === 4 && d.masks[1].closed === 1, d.masks.length);
await ui.click("#propsSec .pick > button");
await ui.locator(".pick-list div", { hasText: "Subtract" }).click();
mv = await matteAt([[1100, 700], [700, 400]]);
check("subtractHole", mv[0] === 0 && mv[1] === 1, mv);
await ui.locator(".mrow").nth(1).locator(".eye").click();
mv = await matteAt([[1100, 700]]);
check("eyeOff", mv[0] === 1, mv);
await ui.locator(".mrow").nth(1).locator(".eye").click();

// 4. feather softens the edge
await ui.locator(".mrow").nth(0).click();
const fb = ui.locator('#propsSec .row[data-k="feather"] input[type=number]');
await fb.fill("80"); await fb.dispatchEvent("change");
mv = await matteAt([[600, 700], [560, 700], [640, 700]]);
check("feather", mv[0] > 0.3 && mv[0] < 0.7 && mv[1] < mv[0] && mv[2] > mv[0], mv);
// feather sits inside / outside the path
await ui.click('#pFpos button[data-v="1"]');
mv = await matteAt([[600, 700], [560, 700], [680, 700]]);
check("featherInside", (await D()).masks[0].fpos === 1 && mv[0] < 0.06 && mv[1] === 0 && mv[2] > 0.9, mv);
await ui.click('#pFpos button[data-v="2"]');
mv = await matteAt([[600, 700], [560, 700], [520, 700]]);
check("featherOutside", mv[0] > 0.94 && mv[1] > 0.3 && mv[1] < 0.7 && mv[2] < 0.06, mv);
await ui.click('#pFpos button[data-v="0"]');
check("fposPacked", await ui.evaluate(() => AMask.decode(AMask.encode(Object.assign(AMask.defaults(), { masks: [Object.assign(AMask.newMask("x"), { fpos: 2 })] }))).masks[0].fpos === 2));

// Shift / Ctrl on panel values: number box Up / Down, Ctrl-drag on the slider is slow
await fb.focus();
await ui.keyboard.press("Shift+ArrowUp");
let fv = (await D()).masks[0].feather;
await ui.keyboard.press("Control+ArrowDown");
let fv2 = (await D()).masks[0].feather;
check("valueSteps", fv === 85 && fv2 === 84.95, [fv, fv2]);
const fsl = await ui.locator('#propsSec .row[data-k="feather"] input[type=range]').boundingBox();
await ui.keyboard.down("Control");
await ui.mouse.move(fsl.x + fsl.width / 2, fsl.y + fsl.height / 2); await ui.mouse.down();
await ui.mouse.move(fsl.x + fsl.width / 2 + 40, fsl.y + fsl.height / 2, { steps: 4 }); await ui.mouse.up();
await ui.keyboard.up("Control");
fv = (await D()).masks[0].feather;
check("sliderFine", fv > fv2 + 2 && fv < fv2 + 25, [fv2, fv]);
await fb.fill("80"); await fb.dispatchEvent("change");

// tooltips: rest the pointer on a button
check("noNativeTitles", await ui.evaluate(() => document.querySelectorAll("[title]").length === 0));
await ui.hover("#savePng");
await ui.waitForTimeout(900);
res.tip = await ui.evaluate(() => [document.getElementById("tip").classList.contains("show"), document.getElementById("tip").textContent]);
check("tooltip", res.tip[0] && /PNG/.test(res.tip[1]), res.tip);
await ui.screenshot({ path: out + "/tooltip.png" });
await ui.hover('#tools button[data-tool="pen"]');
await ui.waitForTimeout(900);
await ui.screenshot({ path: out + "/tooltip_tool.png" });

// 5. select a point, nudge with the arrow keys (1 px, Shift 10 px, Ctrl 0.1 px; steps from Settings)
await ui.click('#tools button[data-tool="select"]');
await click(1600, 1100);
await ui.keyboard.press("ArrowRight");
await ui.keyboard.down("Shift"); await ui.keyboard.press("ArrowRight"); await ui.keyboard.up("Shift");
d = await D();
check("nudge", d.masks[0].pts[2].x === 1611 && d.masks[0].pts[2].y === 1100, d.masks[0].pts[2]);
await ui.keyboard.press("Control+ArrowDown");
d = await D();
check("nudgeCtrl", d.masks[0].pts[2].y === 1100.1, d.masks[0].pts[2]);
await ui.keyboard.press("Control+ArrowUp");
await ui.click("#setBtn");
await ui.waitForSelector("#settings.show");
await ui.screenshot({ path: out + "/settings.png" });
await ui.fill("#sNudge", "5");
await ui.keyboard.press("Enter");
await ui.keyboard.press("ArrowRight");
d = await D();
check("nudgeSetting", d.masks[0].pts[2].x === 1616 && !(await ui.isVisible("#settings")), d.masks[0].pts[2]);
await ui.keyboard.press("ArrowLeft");
await ui.click("#setBtn"); await ui.click("#sReset"); await ui.click("#sClose");
check("settingsReset", (await ui.evaluate(() => window.__am.prefs.nudge)) === 1 && (await D()).masks[0].pts[2].x === 1611);
// marquee selects points
await dragDoc(500, 1000, 1700, 1200);
res.marqueeSel = await ui.evaluate(() => [...window.__am.sel].sort());
check("marquee", res.marqueeSel.join() === "2,3", res.marqueeSel);

// 6. add a point on a line (shape unchanged), delete it with the delete tool, undo
await ui.click('#tools button[data-tool="add"]');
await click(600, 700);                          // left edge, straight line
d = await D();
check("addPoint", d.masks[0].pts.length === 5 && Math.abs(d.masks[0].pts[4].x - 600) < 1, d.masks[0].pts.map((p) => [p.x, p.y]));
await ui.click('#tools button[data-tool="delete"]');
await click(1611, 1100);
d = await D();
check("deletePoint", d.masks[0].pts.length === 4, d.masks[0].pts.length);
await ui.click("#undo");
d = await D();
check("undo", d.masks[0].pts.length === 5, d.masks[0].pts.length);
await ui.click("#redo");
d = await D();
check("redo", d.masks[0].pts.length === 4, d.masks[0].pts.length);

// 7. convert: click toggles corner -> smooth
await ui.click('#tools button[data-tool="convert"]');
await click(600, 300);
d = await D();
check("convertSmooth", d.masks[0].pts[0].s === 1 && (d.masks[0].pts[0].ox || d.masks[0].pts[0].oy), d.masks[0].pts[0]);
await click(600, 300);
d = await D();
check("convertCorner", !d.masks[0].pts[0].ox && !d.masks[0].pts[0].oy, d.masks[0].pts[0]);

// 8. new Web layer, mapping assigned, URL carries the mask
await ui.click("#newLayer");
await ui.waitForSelector("#ask.show");
await ui.fill("#askInput", "Mask stage");
await ui.click("#askBtns button.primary");
await ui.waitForFunction(() => document.getElementById("target").value === "Mask stage", null, { timeout: 8000 });
await ui.waitForTimeout(500);
let w = await world();
check("layerCreated", w.length === 1 && w[0].web && /#name=.*&d=/.test(w[0].url) && w[0].sizeMode === 0, w);
check("layerMapping", w[0].mapping === "feed stage", w[0].mapping);

// 9. the Web layer page renders the same matte
const outp = await ctx.newPage();
outp.on("pageerror", (e) => errs.push("out: " + e.message));
await outp.setViewportSize({ width: 1280, height: 720 });
await outp.goto(w[0].url);
await outp.waitForTimeout(400);
const px = (x, y) => outp.evaluate(([x, y]) => Array.from(document.getElementById("c").getContext("2d").getImageData(x, y, 1, 1).data), [x, y]);
res.outPx = [await px(1400, 400), await px(1100, 700), await px(200, 200)];
check("outPage", res.outPx[0][0] === 255 && res.outPx[1][0] === 0 && res.outPx[2][0] === 0, res.outPx);
await outp.evaluate(() => { window.__marker = 42; });

// 10. live: invert all -> URL rewritten, page redraws without reloading
const url0 = w[0].url;
await ui.click("#oInv button:nth-child(2)");
const t0 = Date.now();
for (;;) { w = await world(); if (w[0].url !== url0 || Date.now() - t0 > 4000) break; await ui.waitForTimeout(25); }
res.pushMs = Date.now() - t0;
await outp.goto(w[0].url);
await outp.waitForTimeout(250);
const inv = await px(200, 200);
check("livePush", w[0].url !== url0 && inv[0] === 255 && (await outp.evaluate(() => window.__marker === 42)), [res.pushMs, inv]);
await ui.click("#oInv button:nth-child(1)");
await ui.waitForTimeout(400);

// 11. reopen the window and pick the layer: the mask set comes back from the layer URL
const ui2 = await ctx.newPage();
ui2.on("pageerror", (e) => errs.push("ui2: " + e.message));
await ui2.goto(base + "/plugins/advanced-masker/index.html");
await ui2.evaluate(() => localStorage.clear());
await ui2.reload();
await ui2.waitForFunction(() => document.getElementById("target").options.length > 1, null, { timeout: 8000 });
await ui2.evaluate(() => { const s = document.getElementById("target"); s.value = "Mask stage"; s.dispatchEvent(new Event("change")); });
await ui2.waitForTimeout(200);
const d2 = await ui2.evaluate(() => JSON.parse(JSON.stringify(window.__am.doc)));
check("restoreFromLayer", d2.masks.length === 2 && d2.w === 2560 && d2.masks[1].mode === "subtract", [d2.masks.length, d2.w]);
await ui2.close();

// 12. exports into objects/VideoFile/masks and objects/DxTexture/masks
await ui.click("#savePng");
await ui.waitForFunction(() => /saved .*\.png/.test(document.getElementById("statusTxt").textContent), null, { timeout: 20000 });
await ui.click('#oFolder button[data-v="DxTexture"]');
await ui.click("#saveTif");
await ui.waitForFunction(() => /saved .*\.tif/.test(document.getElementById("statusTxt").textContent), null, { timeout: 30000 });
const pngPath = path.join(proj, "objects", "VideoFile", "masks", "feed stage_2560x1440.png");
const tifPath = path.join(proj, "objects", "DxTexture", "masks", "feed stage_2560x1440.tif");
check("pngWritten", fs.existsSync(pngPath) && fs.readFileSync(pngPath).slice(1, 4).toString() === "PNG", pngPath);
check("tifWritten", fs.existsSync(tifPath) && fs.readFileSync(tifPath).slice(0, 2).toString() === "II", tifPath);
if (fs.existsSync(pngPath)) fs.copyFileSync(pngPath, path.join(out, "export.png"));

// 13. mask set file
await ui.click("#setSave");
await ui.waitForSelector("#ask.show");
await ui.fill("#askInput", "stage set");
await ui.click("#askBtns button.primary");
await ui.waitForTimeout(500);
const setPath = path.join(proj, "plugins", "advanced-masker", "masks", "stage set.json");
check("setSaved", fs.existsSync(setPath) && JSON.parse(fs.readFileSync(setPath, "utf8")).doc.masks.length === 2, setPath);

await ui.click('#tools button[data-tool="select"]');
await ui.locator(".mrow").nth(0).click();
await ui.click("#ptAll");
await ui.waitForTimeout(100);
await ui.screenshot({ path: out + "/ui.png" });
await ui.click("#vMode button:nth-child(2)");
await ui.waitForTimeout(100);
await ui.screenshot({ path: out + "/ui_matte.png" });
await outp.screenshot({ path: out + "/out.png" });
res.errs = errs;
console.log(JSON.stringify(res, null, 1));
await browser.close();
process.exit(errs.length ? 1 : 0);
