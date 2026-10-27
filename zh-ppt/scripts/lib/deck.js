// 稿子（JSON 对象）-> .pptx。页型的画法在 pages.js，这里管母版、放字、图标、分节和告警。
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { resolveTheme, writeThemeIntoFile } = require("./theme");
const { rich, plain, heightOf } = require("./text");
const PAGES = require("./pages");

const LINE = 1.3; // 估高用的行距倍数，按微软雅黑的字高留了余量

let iconLib = null;
function loadIcons() {
  if (iconLib) return iconLib;
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const sharp = require("sharp");
  const sets = [require("react-icons/fa")];
  try { sets.push(require("react-icons/fa6")); } catch (_) { /* 老版本没有 fa6 */ }
  iconLib = { React, renderToStaticMarkup, sharp, sets };
  return iconLib;
}

async function buildDeck(spec, { baseDir = process.cwd(), out } = {}) {
  if (!spec || !Array.isArray(spec.slides) || spec.slides.length === 0) throw new Error("稿子里没有 slides，至少要有一页");
  const t = resolveTheme(spec.theme);
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9"; // 10 x 5.625 英寸
  pres.title = spec.title || plain(spec.slides[0].title || "演示文稿");
  if (spec.author) pres.author = spec.author;
  if (spec.company) pres.company = spec.company;
  pres.theme = { headFontFace: t.font, bodyFontFace: t.font };

  const footer = spec.footer
    ? [{ text: { text: spec.footer, options: { x: 0.5, y: 5.2, w: 6, h: 0.3, fontSize: 9, fontFace: t.font, color: t.muted, margin: 0, valign: "middle" } } }]
    : [];
  pres.defineSlideMaster({
    title: "封面", background: { color: t.dark },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.6, w: 8.6, h: 1.3, fontSize: 36, bold: true, fontFace: t.font, color: "FFFFFF", align: "left", valign: "bottom", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.05, w: 8.6, h: 0.9, fontSize: 16, fontFace: t.font, color: t.line, align: "left", valign: "top", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "内容", background: { color: "FFFFFF" },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9, h: 0.7, fontSize: 26, bold: true, fontFace: t.font, color: t.dark, align: "left", valign: "middle", margin: 0 }, text: "" } },
      ...footer,
    ],
    slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.3, fontSize: 10, fontFace: t.font, color: t.muted, align: "right" },
  });
  pres.defineSlideMaster({
    title: "结尾", background: { color: t.dark },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 0.6, w: 8.6, h: 0.8, fontSize: 28, bold: true, fontFace: t.font, color: "FFFFFF", align: "left", valign: "middle", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({ title: "空白", background: { color: t.soft } });

  const warnings = [];
  const iconCache = new Map();
  let section = null, slideNo = 0, label = "";

  const ctx = {
    pres, t, baseDir, shapes: pres.shapes,
    warn: (msg) => warnings.push(`${label}${msg}`),

    // 算这段字放进框里该用几号：字多就往小缩，最多缩到 minSize
    fit(content, box, o = {}) {
      const size = o.fontSize || 14, min = o.minSize || Math.max(9, size - 3);
      const measure = o.measureAs || plain(content);
      const hopt = { lineSpacing: LINE, paraAfter: o.paraSpaceAfter || 0, bullet: !!o.bullet };
      let fs = size;
      while (fs > min && heightOf(measure, fs, box.w, hopt) > box.h) fs = Math.round((fs - 0.5) * 2) / 2;
      return { fs, need: heightOf(measure, fs, box.w, hopt), measure };
    },

    // 同一页里同一种字（几张卡片的说明、几行对策）统一字号：取各自能放下的最小那个
    groupSize(list, o = {}) {
      const base = o.fontSize || 14;
      let best = base, worst = null;
      for (const x of list.filter((y) => y.content)) {
        const { fs } = ctx.fit(x.content, x.box, o);
        if (fs < best) { best = fs; worst = x.content; }
      }
      if (best <= base - 3 && !o.quiet) ctx.warn(`「${plain(worst).slice(0, 12)}…」这一组字偏多，整组缩到 ${best} 号（原定 ${base} 号），看着会小，建议删字或拆页`);
      return best;
    },

    // 按框放字；放不下就记一条告警
    text(slide, content, box, o = {}) {
      const size = o.fontSize || 14;
      const { fs, need, measure } = ctx.fit(content, box, o);
      if (need > box.h + 0.02) {
        const extra = Math.ceil((need - box.h) / (fs * LINE / 72));
        ctx.warn(`「${o.name || measure.slice(0, 12)}」字多放不下，缩到 ${fs} 号还超约 ${extra} 行，删字或拆页`);
      }
      let runs = rich(content, o.emphasis === undefined ? t.primary : o.emphasis);
      const k = fs / size;
      runs = runs.map((r) => {
        const op = { ...r.options };
        if (op.fontSize) op.fontSize = Math.round(op.fontSize * k * 2) / 2;
        if (o.bullet && op.bullet === undefined) op.bullet = o.bullet;
        return { text: r.text, options: op };
      });
      slide.addText(runs, {
        x: box.x, y: box.y, w: box.w, h: box.h, fontSize: fs, fontFace: t.font,
        color: o.color || t.text, bold: !!o.bold, italic: !!o.italic, align: o.align || "left",
        valign: o.valign || "top", margin: 0, isTextBox: true, paraSpaceAfter: o.paraSpaceAfter,
        objectName: o.name,
      });
      return fs;
    },

    // 图标：react-icons 里 Font Awesome 的名字，如 FaRocket；找不到就记告警、不画
    async icon(slide, name, box, color = "FFFFFF") {
      if (!name) return false;
      const key = name + "|" + color;
      if (!iconCache.has(key)) {
        const L = loadIcons();
        const Comp = L.sets.map((s) => s[name]).find(Boolean);
        if (!Comp) { ctx.warn(`没有叫 ${name} 的图标（去 react-icons.github.io/react-icons 的 Font Awesome 里找名字）`); iconCache.set(key, null); }
        else {
          const svg = L.renderToStaticMarkup(L.React.createElement(Comp, { color: "#" + color, size: 256 }));
          const buf = await L.sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
          iconCache.set(key, "image/png;base64," + buf.toString("base64"));
        }
      }
      const data = iconCache.get(key);
      if (!data) return false;
      slide.addImage({ data, ...box, objectName: "图标 " + name });
      return true;
    },

    // 开一页内容页并放好标题
    content(title, d, master = "内容") {
      const s = pres.addSlide({ masterName: master, ...(section ? { sectionTitle: section } : {}) });
      slideNo++;
      label = `第 ${slideNo} 页「${plain(title || (d && (d.title || d.text)) || "").slice(0, 16)}」：`;
      if (title) {
        const ph = { 内容: { w: 9, h: 0.7, size: 26, min: 20 }, 结尾: { w: 8.6, h: 0.8, size: 28, min: 22 }, 封面: { w: 8.6, h: 1.3, size: 36, min: 26 } }[master];
        if (ph) {
          let fs = ph.size;
          while (fs > ph.min && heightOf(plain(title), fs, ph.w, { lineSpacing: LINE }) > ph.h) fs -= 1;
          if (heightOf(plain(title), fs, ph.w, { lineSpacing: LINE }) > ph.h) ctx.warn("标题太长，缩到最小号也放不下，标题写成一句结论、控制在 20 字左右");
          s.addText(plain(title), { placeholder: "title", fontSize: fs });
        }
      }
      if (d && d.notes) s.addNotes(String(d.notes));
      return s;
    },
  };

  for (const d of spec.slides) {
    const fn = PAGES[d.type];
    if (!fn) throw new Error(`第 ${slideNo + 1} 页的页型「${d.type}」不认识，可选：${Object.keys(PAGES).join("、")}`);
    if (d.section && d.section !== section) { section = d.section; pres.addSection({ title: section }); }
    await fn(d, ctx);
  }

  const file = out || path.resolve(baseDir, (spec.file || pres.title) + ".pptx");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await pres.writeFile({ fileName: file });
  await writeThemeIntoFile(file, t);
  return { file, slides: slideNo, warnings };
}

module.exports = { buildDeck };
