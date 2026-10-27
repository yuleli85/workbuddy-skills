#!/usr/bin/env python3
"""把 .pptx 转成 PDF 和逐页图片，用来核对版面。

用法：python3 scripts/render.py 演示.pptx [输出目录]
输出：输出目录下 演示.pdf、第01页.png ...、总览.png（所有页拼一张）。
要装：LibreOffice（转 PDF）和 pymupdf（pip install pymupdf，转图片）。
找 LibreOffice 的顺序：环境变量 SOFFICE、PATH 里的 soffice/libreoffice、macOS 默认安装位置。
"""
import os, shutil, subprocess, sys, tempfile


def find_soffice():
    cands = [os.environ.get("SOFFICE"), shutil.which("soffice"), shutil.which("libreoffice"),
             "/Applications/LibreOffice.app/Contents/MacOS/soffice",
             os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
             r"C:\Program Files\LibreOffice\program\soffice.exe"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.splitext(src)[0] + "-出图"
    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]

    soffice = find_soffice()
    if not soffice:
        sys.exit("没找到 LibreOffice。装好后再跑，或用环境变量 SOFFICE 指到 soffice 程序。")
    with tempfile.TemporaryDirectory() as tmp:
        # 单独的用户配置目录，避免和正在开着的 LibreOffice 抢锁
        prof = "file://" + os.path.join(tmp, "profile").replace("\\", "/")
        r = subprocess.run([soffice, f"-env:UserInstallation={prof}", "--headless", "--convert-to", "pdf",
                            "--outdir", tmp, src], capture_output=True, text=True, timeout=300)
        pdf_tmp = os.path.join(tmp, stem + ".pdf")
        if not os.path.exists(pdf_tmp):
            sys.exit("转 PDF 失败：\n" + (r.stderr or r.stdout))
        pdf = os.path.join(out, stem + ".pdf")
        shutil.copy(pdf_tmp, pdf)
    print("PDF：" + pdf)

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            sys.exit("没装 pymupdf，只出了 PDF。要逐页图片：pip install pymupdf")

    doc = pymupdf.open(pdf)
    for i, page in enumerate(doc):
        page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(os.path.join(out, f"第{i + 1:02d}页.png"))
    # 总览：每行 3 页
    cols = 3
    pw, ph = doc[0].rect.width, doc[0].rect.height
    gap = 12
    rows = (len(doc) + cols - 1) // cols
    sheet = pymupdf.open()
    sp = sheet.new_page(width=cols * pw + (cols + 1) * gap, height=rows * ph + (rows + 1) * gap)
    sp.draw_rect(sp.rect, color=None, fill=(0.85, 0.85, 0.85))
    for i in range(len(doc)):
        r, c = divmod(i, cols)
        x, y = gap + c * (pw + gap), gap + r * (ph + gap)
        sp.show_pdf_page(pymupdf.Rect(x, y, x + pw, y + ph), doc, i)
    sp.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(os.path.join(out, "总览.png"))
    print(f"图片：{out}（{len(doc)} 页 + 总览.png）")


if __name__ == "__main__":
    main()
