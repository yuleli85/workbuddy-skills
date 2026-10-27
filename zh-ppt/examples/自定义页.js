// 自定义页示例：页型里没有的版面自己画。slide 已经放好标题，ctx 里有配色和放字、图标工具。
module.exports = async (slide, ctx, d) => {
  const { t, pres } = ctx;
  const vals = d.values; // [{ name, value }]，value 是 0~100
  vals.forEach((v, i) => {
    const y = 1.35 + i * 0.75;
    ctx.text(slide, v.name, { x: 0.5, y, w: 2.2, h: 0.5 }, { fontSize: 15, bold: true, color: t.dark, valign: "middle" });
    slide.addShape(pres.shapes.RECTANGLE, { x: 2.8, y: y + 0.12, w: 6.0, h: 0.26, fill: { color: t.soft }, line: { type: "none" } });
    slide.addShape(pres.shapes.RECTANGLE, { x: 2.8, y: y + 0.12, w: 6.0 * v.value / 100, h: 0.26, fill: { color: t.primary }, line: { type: "none" } });
    ctx.text(slide, v.value + "%", { x: 8.9, y, w: 0.6, h: 0.5 }, { fontSize: 14, bold: true, color: t.primary, align: "right", valign: "middle" });
  });
};
