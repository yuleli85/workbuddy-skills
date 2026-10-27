#!/usr/bin/env node
// 用法：node scripts/build.js 稿子.json [输出.pptx]
// 不写输出路径时，放在稿子旁边，文件名取稿子里的 file，没有就取 title。
const fs = require("fs");
const path = require("path");
const { buildDeck } = require("./lib/deck");

(async () => {
  const [src, out] = process.argv.slice(2);
  if (!src) { console.error("用法：node scripts/build.js 稿子.json [输出.pptx]"); process.exit(2); }
  let spec;
  try { spec = JSON.parse(fs.readFileSync(src, "utf8")); }
  catch (e) { console.error(`稿子读不了：${e.message}`); process.exit(2); }
  const baseDir = path.dirname(path.resolve(src));
  const r = await buildDeck(spec, { baseDir, out: out && path.resolve(out) });
  console.log(`已生成：${r.file}（${r.slides} 页）`);
  if (r.warnings.length) {
    console.log(`\n版面提醒 ${r.warnings.length} 条（改稿子后重跑）：`);
    for (const w of r.warnings) console.log("  - " + w);
    process.exitCode = 3;
  }
})().catch((e) => { console.error("生成失败：" + e.message); process.exit(1); });
