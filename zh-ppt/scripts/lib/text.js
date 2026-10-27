// 中文排版用的两件事：把「**加粗**」写法转成文字段，估算一段字在框里占几行。
// 估算按字号算宽度：汉字和全角标点 1 个字号宽，英文数字约半个。和 PowerPoint 实际排版
// 会差一点，所以放字时留了余量；最终以出图核对为准。

// "第一行**重点**\n第二行" -> pptxgenjs 的文字段数组
function rich(input, emphasis) {
  if (Array.isArray(input)) return input; // 已经是文字段数组，原样用
  const out = [];
  const paras = String(input ?? "").split("\n");
  paras.forEach((p, pi) => {
    const parts = p.split(/(\*\*[^*]+\*\*)/).filter((x) => x !== "");
    if (parts.length === 0) parts.push("");
    parts.forEach((part, k) => {
      const bold = /^\*\*[^*]+\*\*$/.test(part);
      const opt = bold ? { bold: true, ...(emphasis ? { color: emphasis } : {}) } : {};
      if (k === parts.length - 1 && pi < paras.length - 1) opt.breakLine = true;
      out.push({ text: bold ? part.slice(2, -2) : part, options: opt });
    });
  });
  return out;
}

const plain = (input) => Array.isArray(input)
  ? input.map((r) => r.text + (r.options && r.options.breakLine ? "\n" : "")).join("")
  : String(input ?? "").replace(/\*\*/g, "");

function charWidth(ch) {
  const c = ch.codePointAt(0);
  if (c >= 0x2e80 || (c >= 0x3000 && c <= 0x303f) || (c >= 0xff00 && c <= 0xffef)) return 1;
  if (ch === " " || "il.,:;|!'`".includes(ch)) return 0.3;
  if (/[A-Z0-9]/.test(ch)) return 0.62;
  if (c < 0x80) return 0.52;
  return 1;
}

// 一段文字（可带 \n）在给定宽度（英寸）里折成几行
function countLines(text, fontSize, widthIn, bullet = false) {
  const avail = widthIn * 72 - (bullet ? fontSize * 1.6 : 0);
  let lines = 0;
  for (const para of String(text).split("\n")) {
    let w = 0, n = 1;
    for (const ch of para) {
      const cw = charWidth(ch) * fontSize;
      if (w + cw > avail + 0.5) { n++; w = cw; } else w += cw;
    }
    lines += n;
  }
  return lines;
}

function heightOf(text, fontSize, widthIn, { lineSpacing = 1.22, paraAfter = 0, bullet = false } = {}) {
  const paras = String(text).split("\n").length;
  return countLines(text, fontSize, widthIn, bullet) * fontSize * lineSpacing / 72 + (paras - 1) * paraAfter / 72;
}

module.exports = { rich, plain, countLines, heightOf, charWidth };
