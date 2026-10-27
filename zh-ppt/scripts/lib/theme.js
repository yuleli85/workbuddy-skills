// 配色方案和主题写回。
// 每套配色 12 个色名，页面直接用十六进制色；生成完再把同一套色写进 .pptx 的主题，
// 这样在 PowerPoint 里改稿时，「主题颜色」面板里看到的就是这套色。
const fs = require("fs");
const path = require("path");

const PRESETS = {
  青绿: {
    primary: "1F8A70", highlight: "F2A541", dark: "12343B", text: "1A2B2E",
    soft: "EEF5F1", line: "D6E9E0", muted: "6B7C7E", light: "5BB89A",
    warn: "C0504D", darkCard: "1D4A52", warnSoft: "FBECEB", highlightSoft: "FCEBCF",
  },
  商务蓝: {
    primary: "1F5FAE", highlight: "F2A541", dark: "14284B", text: "1E2A3A",
    soft: "EEF3FA", line: "D3E0F0", muted: "6B7685", light: "5B8FD6",
    warn: "C0504D", darkCard: "1E3A66", warnSoft: "FBECEB", highlightSoft: "FCEBCF",
  },
  石墨橙: {
    primary: "D9692A", highlight: "F2C14E", dark: "2B2F36", text: "25282D",
    soft: "F3F1EE", line: "E2DDD6", muted: "7A7F87", light: "EFA46A",
    warn: "B23A3A", darkCard: "3A3F48", warnSoft: "F8E6E6", highlightSoft: "FDF1D6",
  },
};
const KEYS = Object.keys(PRESETS["青绿"]);

// theme 可以是预设名，也可以是 { base: "商务蓝", primary: "..." } 这样的覆盖
function resolveTheme(theme) {
  let base = "青绿", over = {};
  if (typeof theme === "string") base = theme;
  else if (theme && typeof theme === "object") { base = theme.base || base; over = theme; }
  if (!PRESETS[base]) throw new Error(`没有叫「${base}」的配色，可选：${Object.keys(PRESETS).join("、")}`);
  const t = { ...PRESETS[base] };
  for (const k of KEYS) {
    if (over[k] === undefined) continue;
    const v = String(over[k]).replace(/^#/, "").toUpperCase();
    if (!/^[0-9A-F]{6}$/.test(v)) throw new Error(`配色「${k}」要写成六位十六进制，比如 1F8A70，现在是 ${over[k]}`);
    t[k] = v;
  }
  t.font = (theme && theme.font) || "Microsoft YaHei";
  t.name = (theme && theme.name) || (typeof theme === "string" ? theme : base);
  return t;
}

function loadJSZip() {
  const base = path.dirname(require.resolve("pptxgenjs"));
  return require(require.resolve("jszip", { paths: [base] }));
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

async function writeThemeIntoFile(file, t) {
  const JSZip = loadJSZip();
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const names = Object.keys(zip.files).filter((n) => /^ppt\/theme\/theme\d+\.xml$/.test(n));
  const slot = {
    dk1: t.text, lt1: "FFFFFF", dk2: t.dark, lt2: t.soft,
    accent1: t.primary, accent2: t.highlight, accent3: t.light, accent4: t.muted,
    accent5: t.line, accent6: t.warn, hlink: t.primary, folHlink: t.muted,
  };
  const scheme = `<a:clrScheme name="${esc(t.name)}">` +
    Object.entries(slot).map(([k, v]) => `<a:${k}><a:srgbClr val="${v}"/></a:${k}>`).join("") +
    `</a:clrScheme>`;
  for (const n of names) {
    let xml = await zip.file(n).async("string");
    xml = xml.replace(/<a:clrScheme[\s\S]*?<\/a:clrScheme>/, scheme);
    xml = xml.replace(/(<a:theme\b[^>]*\bname=")[^"]*"/, `$1${esc(t.name)}"`);
    // 标题、正文字体的中文槽位也填上，免得 PowerPoint 回落到等线
    xml = xml.replace(/(<a:(?:major|minor)Font>\s*<a:latin typeface=")[^"]*("\/>\s*<a:ea typeface=")[^"]*"/g,
      `$1${esc(t.font)}$2${esc(t.font)}"`);
    zip.file(n, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

module.exports = { PRESETS, resolveTheme, writeThemeIntoFile };
