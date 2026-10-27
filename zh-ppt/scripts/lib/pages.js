// 页型。每个页型是 async (d, ctx)：d 是稿子里这一页的内容，ctx 见 deck.js。
// 版面是 16:9（10 x 5.625 英寸），内容区左右各留 0.5，标题下从 1.15 开始，底到 5.1。
const path = require("path");
const { rich, plain, heightOf } = require("./text");

const X0 = 0.5, W = 9, TOP = 1.15, BOTTOM = 5.1;
const pad2 = (i) => String(i + 1).padStart(2, "0");
const need = (d, key, type) => {
  if (!Array.isArray(d[key]) || d[key].length === 0) throw new Error(`页型 ${type} 要有 ${key}（数组），这一页「${plain(d.title || "")}」没写`);
  return d[key];
};
const noLine = { type: "none" };

// ---------- 封面 ----------
async function cover(d, ctx) {
  const { t } = ctx;
  const s = ctx.content(d.title, d, "封面");
  if (d.subtitle) s.addText(plain(d.subtitle), { placeholder: "body" });
  await ctx.icon(s, d.icon, { x: 0.7, y: 0.75, w: 0.6, h: 0.6 }, t.light);
  if (d.meta) ctx.text(s, d.meta, { x: 0.7, y: 4.75, w: 8.6, h: 0.35 }, { fontSize: 12, color: t.light, name: "封面落款" });
}

// ---------- 一句话大字页 ----------
async function statement(d, ctx) {
  const { t, pres } = ctx;
  const s = ctx.content(null, d, "空白");
  s.addShape(pres.shapes.RECTANGLE, { x: 0.9, y: 1.45, w: 0.08, h: 2.2, fill: { color: t.primary }, line: noLine, objectName: "竖线" });
  ctx.text(s, d.text || d.title, { x: 1.2, y: 1.35, w: 7.9, h: 2.4 }, { fontSize: 30, minSize: 20, bold: true, color: t.dark, valign: "middle", name: "大字" });
  if (d.sub) ctx.text(s, d.sub, { x: 1.2, y: 3.95, w: 7.9, h: 0.8 }, { fontSize: 15, color: t.muted, name: "大字补充" });
}

// ---------- 流程 / 闭环 ----------
async function flow(d, ctx) {
  const { t, pres } = ctx;
  const steps = need(d, "steps", "flow");
  const s = ctx.content(d.title, d);
  const n = steps.length, hasDesc = steps.some((x) => x.desc);
  if (d.intro) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y: TOP, w: W, h: 1.25, fill: { color: t.soft }, line: noLine, rectRadius: 0.08, objectName: "引言底" });
    ctx.text(s, d.intro, { x: X0 + 0.2, y: TOP + 0.08, w: W - 0.4, h: 1.09 }, { fontSize: 14, minSize: 11, valign: "middle", name: "引言" });
  }
  const dm = Math.min(0.9, (W - (n - 1) * 0.45) / n);
  const gap = n > 1 ? (W - dm * n) / (n - 1) : 0;
  const y = d.intro ? (hasDesc ? 2.55 : 2.75) : (hasDesc ? 1.95 : 2.2);
  const tw = Math.min(dm + gap * 0.8, 2.2);
  const sName = ctx.groupSize(steps.map((it) => ({ content: it.name, box: { w: tw, h: 0.36 } })), { fontSize: 15, minSize: 11 });
  const sDesc = ctx.groupSize(steps.map((it) => ({ content: it.desc, box: { w: tw, h: 0.72 } })), { fontSize: 11, minSize: 9 });
  for (let i = 0; i < n; i++) {
    const it = steps[i], x = X0 + i * (dm + gap);
    s.addShape(pres.shapes.OVAL, { x, y, w: dm, h: dm, fill: { color: it.key ? t.highlight : t.primary }, line: noLine, objectName: "环节圈" + (i + 1) });
    const drew = await ctx.icon(s, it.icon, { x: x + dm * 0.3, y: y + dm * 0.3, w: dm * 0.4, h: dm * 0.4 });
    if (!drew) ctx.text(s, String(i + 1), { x, y, w: dm, h: dm }, { fontSize: 22, bold: true, color: "FFFFFF", align: "center", valign: "middle", name: "环节号" + (i + 1) });
    ctx.text(s, it.name, { x: x + dm / 2 - tw / 2, y: y + dm + 0.08, w: tw, h: 0.36 }, { fontSize: sName, minSize: sName, bold: true, color: t.dark, align: "center", name: "环节名" + (i + 1) });
    if (it.desc) ctx.text(s, it.desc, { x: x + dm / 2 - tw / 2, y: y + dm + 0.46, w: tw, h: 0.72 }, { fontSize: sDesc, minSize: sDesc, color: t.text, align: "center", name: "环节说明" + (i + 1) });
    if (i < n - 1 && d.arrows !== false) {
      s.addShape(pres.shapes.RIGHT_ARROW, { x: x + dm + gap * 0.2, y: y + dm / 2 - 0.1, w: gap * 0.6, h: 0.2, fill: { color: t.line }, line: noLine, objectName: "箭头" + (i + 1) });
    }
  }
  if (d.note) ctx.text(s, d.note, { x: X0, y: 4.55, w: W - 0.6, h: 0.5 }, { fontSize: 14, minSize: 11, name: "流程说明" });
}

// ---------- 卡片墙 ----------
async function cards(d, ctx) {
  const { t, pres } = ctx;
  const items = need(d, "items", "cards");
  const s = ctx.content(d.title, d);
  const n = items.length;
  const cols = d.columns || (n <= 4 ? n : n <= 6 ? 3 : n <= 8 ? 4 : 5);
  const rows = Math.ceil(n / cols);
  const hasKey = items.some((x) => x.key);
  const bottom = (d.legend && hasKey) || d.note ? 4.78 : BOTTOM;
  const gx = cols >= 5 ? 0.2 : 0.25, gy = 0.22;
  const outline = d.style === "outline";
  const big = cols <= 3, hero = rows === 1 && cols <= 4; // 一排几张大卡：图标和字都放大
  const cw = (W - gx * (cols - 1)) / cols, ch = Math.min(hero ? 3.3 : 2.6, (bottom - TOP - gy * (rows - 1)) / rows);
  const cd = hero ? 0.8 : big ? 0.6 : 0.5, numW = d.numbered ? 0.75 : 0.14;
  const nameSize = hero ? (big ? 22 : 18) : big ? 17 : cols >= 5 ? 13 : 15;
  const descSize = hero ? (big ? 15 : 13) : big ? 13 : cols >= 5 ? 11 : 12;
  // 两种排法：图标在上、名字在下（竖排），或图标和名字一行、说明占下面整块（横排）
  const geo = (inline, x, y) => inline
    ? { name: { x: x + 0.16 + cd + 0.12, y: y + 0.16, w: cw - (0.16 + cd + 0.12) - numW, h: cd },
        desc: { x: x + 0.16, y: y + 0.16 + cd + 0.12, w: cw - 0.32, h: ch - cd - 0.4 } }
    : { name: { x: x + 0.14, y: y + 0.16 + cd + 0.14, w: cw - 0.28, h: 0.44 },
        desc: { x: x + 0.14, y: y + 0.16 + cd + 0.62, w: cw - 0.28, h: ch - cd - 0.9 } };
  const sizes = (inline, quiet) => {
    const g = geo(inline, 0, 0);
    return {
      name: ctx.groupSize(items.map((it) => ({ content: it.name, box: g.name })), { fontSize: nameSize, minSize: 10, quiet }),
      desc: ctx.groupSize(items.map((it) => ({ content: it.desc, box: g.desc })), { fontSize: descSize, minSize: 9, quiet }),
    };
  };
  let inline = d.layout === "inline" || (d.layout !== "stack" && ch < 1.45);
  if (!d.layout && !inline) {
    const a = sizes(false, true), b = sizes(true, true);
    if (a.desc < descSize && b.desc > a.desc) inline = true;
  }
  const sz = sizes(inline, false);
  for (let i = 0; i < n; i++) {
    const it = items[i], r = Math.floor(i / cols), c = i % cols;
    const x = X0 + c * (cw + gx), y = TOP + r * (ch + gy);
    const fill = it.key ? (outline ? t.highlightSoft : t.highlight) : (outline ? "FFFFFF" : t.soft);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w: cw, h: ch, fill: { color: fill }, rectRadius: 0.08, objectName: "卡片" + (i + 1),
      line: outline ? { color: it.key ? t.highlight : t.line, width: 1 } : noLine,
      ...(outline ? { shadow: { type: "outer", color: "000000", opacity: 0.08, blur: 6, offset: 2, angle: 90 } } : {}),
    });
    const circle = it.key && !outline ? t.dark : t.primary;
    s.addShape(pres.shapes.OVAL, { x: x + 0.16, y: y + 0.16, w: cd, h: cd, fill: { color: circle }, line: noLine, objectName: "卡片圈" + (i + 1) });
    const drew = await ctx.icon(s, it.icon, { x: x + 0.16 + cd * 0.26, y: y + 0.16 + cd * 0.26, w: cd * 0.48, h: cd * 0.48 });
    if (!drew && !d.numbered) ctx.text(s, String(i + 1), { x: x + 0.16, y: y + 0.16, w: cd, h: cd }, { fontSize: 16, bold: true, color: "FFFFFF", align: "center", valign: "middle", name: "卡片号" + (i + 1) });
    if (d.numbered) {
      ctx.text(s, pad2(i), { x: x + cw - 0.75, y: y + 0.16, w: 0.6, h: cd }, { fontSize: 18, bold: true, color: it.key && !outline ? t.dark : t.light, align: "right", valign: "middle", name: "卡片编号" + (i + 1) });
    }
    const g = geo(inline, x, y);
    ctx.text(s, it.name, g.name, { fontSize: sz.name, minSize: sz.name, bold: true, color: t.dark, valign: "middle", name: "卡片名" + (i + 1) });
    if (it.desc) ctx.text(s, it.desc, g.desc, { fontSize: sz.desc, minSize: sz.desc, name: "卡片说明" + (i + 1) });
  }
  if (d.legend && hasKey) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y: 4.95, w: 0.3, h: 0.22, fill: { color: outline ? t.highlightSoft : t.highlight }, line: outline ? { color: t.highlight, width: 1 } : noLine, rectRadius: 0.04, objectName: "图例块" });
    ctx.text(s, d.legend, { x: X0 + 0.4, y: 4.9, w: 7.6, h: 0.32 }, { fontSize: 12, minSize: 10, valign: "middle", name: "图例" });
  } else if (d.note) {
    ctx.text(s, d.note, { x: X0, y: 4.9, w: 8.2, h: 0.32 }, { fontSize: 12, minSize: 10, valign: "middle", name: "卡片页说明" });
  }
}

// ---------- 表格（太长自动拆成几页）----------
async function table(d, ctx) {
  const { t } = ctx;
  const cols = need(d, "columns", "table"), rows = need(d, "rows", "table");
  const totalW = cols.reduce((a, c) => a + (c.width || 1), 0);
  const colW = cols.map((c) => ((c.width || 1) / totalW) * W);
  const fs = d.fontSize || 12, CELL_PAD = 0.2, HEAD = 0.42;
  const key = new Set(d.keyRows || []);
  const cellText = (r, i, c) => (c === 0 && d.numbered ? `${pad2(i)}  ` : "") + plain(r[c] ?? "");
  const rowH = rows.map((r, i) => Math.max(0.42, ...cols.map((_, c) => heightOf(cellText(r, i, c), fs, colW[c] - CELL_PAD, { lineSpacing: 1.3 }) + 0.16)));
  const avail = (d.note ? 4.95 : 5.15) - TOP - HEAD;
  // 先贪心装页，再看能不能按条数平均分，免得最后一页只剩一两行
  const pages = [];
  let cur = [], h = 0;
  rows.forEach((_, i) => {
    if (cur.length && h + rowH[i] > avail) { pages.push(cur); cur = []; h = 0; }
    cur.push(i); h += rowH[i];
  });
  if (cur.length) pages.push(cur);
  if (pages.length > 1) {
    const per = Math.ceil(rows.length / pages.length);
    const even = [];
    for (let i = 0; i < rows.length; i += per) even.push(rows.map((_, k) => k).slice(i, i + per));
    if (even.length === pages.length && even.every((p) => p.reduce((a, k) => a + rowH[k], 0) <= avail)) pages.splice(0, pages.length, ...even);
  }
  const tone = (c) => (c.color === "warn" ? t.warn : c.color === "primary" ? t.primary : c.color === "muted" ? t.muted : null);
  for (let p = 0; p < pages.length; p++) {
    const title = pages.length > 1 ? `${plain(d.title)}（${p + 1}/${pages.length}）` : d.title;
    const s = ctx.content(title, p === 0 ? d : null);
    const hdr = cols.map((c) => ({ text: c.name, options: { bold: true, color: "FFFFFF", fill: { color: t.dark }, fontSize: fs + 1 } }));
    const body = pages[p].map((i, z) => {
      const fill = { color: key.has(i) ? t.highlightSoft : z % 2 ? "FFFFFF" : t.soft };
      return cols.map((c, k) => ({
        text: cellText(rows[i], i, k),
        options: { fill, bold: k === 0, color: k === 0 ? t.dark : tone(c) || t.text },
      }));
    });
    s.addTable([hdr, ...body], {
      x: X0, y: TOP, w: W, colW, fontSize: fs, fontFace: t.font, valign: "middle", autoPage: false,
      border: { type: "solid", pt: 0.75, color: t.line }, margin: [0.06, 0.1, 0.06, 0.1],
      rowH: [HEAD, ...pages[p].map((i) => rowH[i])], objectName: "表格" + (p + 1),
    });
    if (pages[p].some((i) => rowH[i] > avail)) ctx.warn("有一行字太多，一页都放不下，删字或把这一格拆短");
    if (d.note) ctx.text(s, d.note, { x: X0, y: 5.08, w: 8.2, h: 0.3 }, { fontSize: 10, color: t.muted, name: "表注" });
  }
}

// ---------- 两三块大面板 ----------
async function panels(d, ctx) {
  const { t, pres } = ctx;
  const items = need(d, "items", "panels");
  const s = ctx.content(d.title, d);
  const n = items.length, g = 0.3, w = (W - g * (n - 1)) / n, y = 1.2, h = 3.75;
  for (let i = 0; i < n; i++) {
    const it = items[i], x = X0 + i * (w + g);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: t.soft }, line: noLine, rectRadius: 0.1, objectName: "面板" + (i + 1) });
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: y + 0.3, w: 0.7, h: 0.7, fill: { color: t.primary }, line: noLine, objectName: "面板圈" + (i + 1) });
    await ctx.icon(s, it.icon, { x: x + 0.48, y: y + 0.48, w: 0.34, h: 0.34 });
    ctx.text(s, it.name, { x: x + 1.2, y: y + 0.3, w: w - 1.5, h: 0.7 }, { fontSize: 22, minSize: 15, bold: true, color: t.dark, valign: "middle", name: "面板名" + (i + 1) });
    let by = y + 1.2;
    if (it.desc) { ctx.text(s, it.desc, { x: x + 0.3, y: by, w: w - 0.6, h: 0.5 }, { fontSize: 14, minSize: 11, valign: "middle", name: "面板说明" + (i + 1) }); by += 0.6; }
    if (it.bullets && it.bullets.length) {
      ctx.text(s, it.bullets.join("\n"), { x: x + 0.3, y: by, w: w - 0.6, h: y + h - by - 0.2 }, { fontSize: 15, minSize: 11, bold: true, color: t.primary, bullet: true, paraSpaceAfter: 6, emphasis: null, name: "面板要点" + (i + 1) });
    }
  }
}

// ---------- 台阶分级 ----------
async function levels(d, ctx) {
  const { t, pres } = ctx;
  const items = need(d, "items", "levels");
  const s = ctx.content(d.title, d);
  const n = items.length, g = 0.15, cw = (W - g * (n - 1)) / n, base = 5.0, h0 = 2.0;
  const step = n > 1 ? Math.min(0.45, (3.75 - h0) / (n - 1)) : 0;
  const stateBox = { w: cw - 0.24, h: 0.72 }, humanBox = { w: cw - 0.24, h: 0.55 };
  const sState = ctx.groupSize(items.map((it) => ({ content: it.state, box: stateBox })), { fontSize: 12, minSize: 9.5 });
  const sHuman = ctx.groupSize(items.map((it) => ({ content: it.human, box: humanBox })), { fontSize: 10.5, minSize: 9 });
  for (let i = 0; i < n; i++) {
    const it = items[i], h = h0 + i * step, x = X0 + i * (cw + g), y = base - h;
    const target = i === d.target;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h, fill: { color: target ? t.highlight : i === n - 1 ? t.line : t.soft }, line: noLine, rectRadius: 0.06, objectName: "台阶" + (i + 1) });
    ctx.text(s, it.level, { x: x + 0.12, y: y + 0.1, w: cw - 0.24, h: 0.5 }, { fontSize: 24, minSize: 14, bold: true, color: target ? t.dark : t.primary, valign: "middle", name: "级别" + (i + 1) });
    ctx.text(s, it.state, { x: x + 0.12, y: y + 0.65, ...stateBox }, { fontSize: sState, minSize: sState, bold: true, color: t.dark, name: "级别状态" + (i + 1) });
    if (it.human) ctx.text(s, it.human, { x: x + 0.12, y: y + 1.4, ...humanBox }, { fontSize: sHuman, minSize: sHuman, name: "级别补充" + (i + 1) });
  }
  if (d.note) ctx.text(s, d.note, { x: X0, y: 1.2, w: Math.max(2.5, (n - 2) * (cw + g) - 0.1), h: 0.85 }, { fontSize: 14, minSize: 11, name: "分级建议" });
}

// ---------- 左问题右对策 ----------
async function compare(d, ctx) {
  const { t, pres } = ctx;
  const rows = need(d, "rows", "compare");
  const s = ctx.content(d.title, d);
  const lw = 4.0, rx = 5.0, rw = 4.5;
  ctx.text(s, d.left || "问题", { x: X0, y: 1.1, w: lw, h: 0.3 }, { fontSize: 12, bold: true, color: t.warn, name: "左列头" });
  ctx.text(s, d.right || "对策", { x: rx, y: 1.1, w: rw, h: 0.3 }, { fontSize: 12, bold: true, color: t.primary, name: "右列头" });
  const n = rows.length, g = 0.1, y0 = 1.45;
  const rh = Math.min(0.85, (5.15 - y0 - g * (n - 1)) / n);
  const leftOf = (it) => plain(it.name) + (it.desc ? "\n" + plain(it.desc) : "");
  const sL = ctx.groupSize(rows.map((it) => ({ content: leftOf(it), box: { w: lw - 0.3, h: rh - 0.08 } })), { fontSize: 14, minSize: 10 });
  const sR = ctx.groupSize(rows.map((it) => ({ content: it.answer, box: { w: rw - 0.3, h: rh - 0.08 } })), { fontSize: 13, minSize: 10 });
  for (let i = 0; i < n; i++) {
    const it = rows[i], y = y0 + i * (rh + g);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y, w: lw, h: rh, fill: { color: t.warnSoft }, line: noLine, rectRadius: 0.06, objectName: "左底" + (i + 1) });
    const left = it.desc ? [
      { text: plain(it.name), options: { bold: true, color: t.warn, breakLine: true } },
      { text: plain(it.desc), options: { fontSize: 11, color: t.text } },
    ] : [{ text: plain(it.name), options: { bold: true, color: t.warn } }];
    ctx.text(s, left, { x: X0 + 0.15, y: y + 0.04, w: lw - 0.3, h: rh - 0.08 }, { fontSize: sL, minSize: sL, valign: "middle", measureAs: leftOf(it), name: "左" + (i + 1) });
    s.addShape(pres.shapes.RIGHT_ARROW, { x: 4.6, y: y + rh / 2 - 0.1, w: 0.3, h: 0.2, fill: { color: t.muted }, line: noLine, objectName: "箭头" + (i + 1) });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: rx, y, w: rw, h: rh, fill: { color: t.soft }, line: noLine, rectRadius: 0.06, objectName: "右底" + (i + 1) });
    ctx.text(s, it.answer, { x: rx + 0.15, y: y + 0.04, w: rw - 0.3, h: rh - 0.08 }, { fontSize: sR, minSize: sR, color: t.dark, valign: "middle", name: "右" + (i + 1) });
  }
}

// ---------- 分步走 ----------
async function steps(d, ctx) {
  const { t, pres } = ctx;
  const items = need(d, "items", "steps");
  const s = ctx.content(d.title, d);
  const n = items.length, gx = 0.3, cw = (W - gx * (n - 1)) / n, y = 1.2, h = 3.6;
  const anyPoint = items.some((it) => it.point), bodyH = anyPoint ? 1.05 : 1.95;
  const sBody = ctx.groupSize(items.map((it) => ({ content: it.body, box: { w: cw - 0.5, h: bodyH } })), { fontSize: 13, minSize: 10 });
  const sPoint = ctx.groupSize(items.map((it) => ({ content: it.point, box: { w: cw - 0.5, h: 0.8 } })), { fontSize: 12, minSize: 9.5 });
  for (let i = 0; i < n; i++) {
    const it = items[i], x = X0 + i * (cw + gx), dark = i === 0 && d.emphasizeFirst !== false;
    const fg = dark ? "FFFFFF" : t.dark;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h, fill: { color: dark ? t.dark : t.soft }, line: noLine, rectRadius: 0.1, objectName: "步骤卡" + (i + 1) });
    ctx.text(s, pad2(i), { x: x + 0.25, y: y + 0.2, w: 1.2, h: 0.75 }, { fontSize: 40, bold: true, color: dark ? t.highlight : t.primary, valign: "middle", name: "步骤号" + (i + 1) });
    if (it.tag) ctx.text(s, it.tag, { x: x + 1.3, y: y + 0.3, w: cw - 1.5, h: 0.55 }, { fontSize: 12, minSize: 9, color: dark ? t.line : t.muted, align: "right", valign: "middle", name: "步骤标签" + (i + 1) });
    ctx.text(s, it.name, { x: x + 0.25, y: y + 1.0, w: cw - 0.5, h: 0.5 }, { fontSize: 20, minSize: 14, bold: true, color: fg, valign: "middle", name: "步骤名" + (i + 1) });
    if (it.body) ctx.text(s, it.body, { x: x + 0.25, y: y + 1.6, w: cw - 0.5, h: bodyH }, { fontSize: sBody, minSize: sBody, color: fg, emphasis: dark ? t.highlight : t.primary, name: "步骤做法" + (i + 1) });
    if (it.point) ctx.text(s, it.point, { x: x + 0.25, y: y + 2.7, w: cw - 0.5, h: 0.8 }, { fontSize: sPoint, minSize: sPoint, italic: true, color: dark ? t.line : t.primary, name: "步骤要点" + (i + 1) });
    if (i < n - 1) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + cw + gx * 0.15, y: y + h / 2 - 0.12, w: gx * 0.7, h: 0.24, fill: { color: t.highlight }, line: noLine, objectName: "步骤箭头" + (i + 1) });
  }
}

// ---------- 要点列表 ----------
async function bullets(d, ctx) {
  const { t, pres } = ctx;
  const items = need(d, "items", "bullets");
  const s = ctx.content(d.title, d);
  const lines = [];
  for (const it of items) {
    if (typeof it === "string") lines.push({ text: it, lvl: 0 });
    else { lines.push({ text: it.text, lvl: 0 }); for (const sub of it.sub || []) lines.push({ text: sub, lvl: 1 }); }
  }
  const hasSide = !!d.callout;
  const w = hasSide ? 5.7 : W;
  const runs = [];
  lines.forEach((ln, k) => {
    const parts = rich(ln.text, t.primary);
    parts.forEach((r, j) => {
      const o = { ...r.options, bullet: ln.lvl ? { indent: 18 } : true, indentLevel: ln.lvl, breakLine: j === parts.length - 1 && k < lines.length - 1 };
      if (ln.lvl) { o.fontSize = undefined; o.color = o.color || t.muted; }
      runs.push({ text: r.text, options: o });
    });
  });
  ctx.text(s, runs, { x: X0, y: TOP + 0.1, w, h: BOTTOM - TOP - 0.2 }, {
    fontSize: d.fontSize || 18, minSize: 12, paraSpaceAfter: 8, bullet: true,
    measureAs: lines.map((l) => (l.lvl ? "　　" : "") + plain(l.text)).join("\n"), name: "要点",
  });
  if (hasSide) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 6.5, y: TOP + 0.1, w: 3.0, h: 3.7, fill: { color: t.dark }, line: noLine, rectRadius: 0.1, objectName: "旁注底" });
    ctx.text(s, d.callout, { x: 6.75, y: TOP + 0.35, w: 2.5, h: 3.2 }, { fontSize: 18, minSize: 12, bold: true, color: "FFFFFF", emphasis: t.highlight, valign: "middle", name: "旁注" });
  }
}

// ---------- 图片页（截图、示意图）----------
async function image(d, ctx) {
  const { t } = ctx;
  const s = ctx.content(d.title, d);
  const file = path.resolve(ctx.baseDir, d.path || "");
  let iw = 16, ih = 9;
  try { const sz = require("image-size"); const f = sz.imageSize || sz.default || sz; const r = f(require("fs").readFileSync(file)); iw = r.width; ih = r.height; }
  catch (e) { ctx.warn(`图片读不到：${d.path}`); return; }
  const boxH = (d.caption ? 4.75 : 5.1) - TOP, k = Math.min(W / iw, boxH / ih);
  const w = iw * k, h = ih * k;
  s.addImage({ path: file, x: X0 + (W - w) / 2, y: TOP + (boxH - h) / 2, w, h, objectName: "图片" });
  if (d.caption) ctx.text(s, d.caption, { x: X0, y: 4.8, w: W, h: 0.35 }, { fontSize: 12, color: t.muted, align: "center", name: "图注" });
}

// ---------- 结尾 ----------
async function closing(d, ctx) {
  const { t, pres } = ctx;
  const items = d.items || [];
  if (!items.length) {
    const s = ctx.content(null, d, "结尾");
    ctx.text(s, d.title, { x: 0.7, y: 1.7, w: 8.6, h: 1.3 }, { fontSize: 40, minSize: 26, bold: true, color: "FFFFFF", valign: "bottom", emphasis: t.highlight, name: "结尾标题" });
    if (d.subtitle) ctx.text(s, d.subtitle, { x: 0.7, y: 3.15, w: 8.6, h: 0.8 }, { fontSize: 16, minSize: 12, color: t.line, name: "结尾小标" });
    return;
  }
  const s = ctx.content(d.title, d, "结尾");
  if (d.subtitle) ctx.text(s, d.subtitle, { x: 0.7, y: 1.6, w: 8.6, h: 0.4 }, { fontSize: 14, color: t.line, name: "结尾小标" });
  const n = items.length;
  if (!n) return;
  const cw = Math.min(2.7, (8.6 - 0.25 * (n - 1)) / n), gx = n > 1 ? (8.6 - cw * n) / (n - 1) : 0;
  const sDesc = ctx.groupSize(items.map((it) => ({ content: it.desc, box: { w: cw - 0.6, h: 0.5 } })), { fontSize: 13, minSize: 10 });
  for (let i = 0; i < n; i++) {
    const it = items[i], x = 0.7 + i * (cw + gx), y = 2.2;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: 2.2, fill: { color: t.darkCard }, line: noLine, rectRadius: 0.1, objectName: "结尾卡" + (i + 1) });
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: y + 0.3, w: 0.7, h: 0.7, fill: { color: t.highlight }, line: noLine, objectName: "结尾圈" + (i + 1) });
    const drew = await ctx.icon(s, it.icon, { x: x + 0.48, y: y + 0.48, w: 0.34, h: 0.34 }, t.dark);
    if (!drew) ctx.text(s, String(i + 1), { x: x + 0.3, y: y + 0.3, w: 0.7, h: 0.7 }, { fontSize: 20, bold: true, color: t.dark, align: "center", valign: "middle", name: "结尾号" + (i + 1) });
    ctx.text(s, it.name, { x: x + 0.3, y: y + 1.15, w: cw - 0.6, h: 0.45 }, { fontSize: 18, minSize: 13, bold: true, color: "FFFFFF", valign: "middle", name: "结尾名" + (i + 1) });
    if (it.desc) ctx.text(s, it.desc, { x: x + 0.3, y: y + 1.6, w: cw - 0.6, h: 0.5 }, { fontSize: sDesc, minSize: sDesc, color: t.line, name: "结尾说明" + (i + 1) });
  }
}

// ---------- 自定义页：稿子里写 script，指向一个导出 async (slide, ctx, d) 的 js 文件 ----------
async function custom(d, ctx) {
  if (!d.script) throw new Error("custom 页要写 script（相对稿子文件的 js 路径）");
  const s = ctx.content(d.title, d);
  await require(path.resolve(ctx.baseDir, d.script))(s, ctx, d);
}

module.exports = { cover, statement, flow, cards, table, panels, levels, compare, steps, bullets, image, closing, custom };
