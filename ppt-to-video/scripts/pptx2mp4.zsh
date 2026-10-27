#!/bin/zsh
# ppt-to-video：把单个 pptx 转成 1080p 幻灯片视频（每页 5 秒，无声）
# 用法: ./pptx2mp4.zsh <文件.pptx> [每页秒数，默认 5]

set -e
setopt NULL_GLOB
SRC="${1:?用法: pptx2mp4.zsh <文件.pptx> [每页秒数]}"
DUR="${2:-5}"
NAME="$(basename "$SRC" | sed 's/\.[^.]*$//')"
WORK="$HOME/WorkBuddy/2026-10-19-20-42-00/ppt2video/$NAME"
mkdir -p "$WORK"

SOFFICE="$HOME/Applications/LibreOffice.app/Contents/MacOS/soffice"
[ -x "$SOFFICE" ] || SOFFICE="$(command -v soffice)"

echo "[1/3] PPT → PDF..."
"$SOFFICE" --headless --convert-to pdf --outdir "$WORK" "$SRC" >/dev/null

echo "[2/3] PDF → 逐页 PNG (1920x1080)..."
(cd "$WORK" && pdftoppm -png -r 144 "$NAME.pdf" slide)

echo "[3/3] 合成 MP4..."
inputs=(); filter=""; i=0
for f in "$WORK"/slide-*.png; do
  inputs+=("-loop" "1" "-t" "$DUR" "-i" "$f")
  filter+="[$i:v]format=yuv420p[v$i];"
  i=$((i+1))
done
for ((j=0; j<i; j++)); do filter+="[v$j]"; done
filter+="concat=n=$i:v=1:a=0[outv]"

ffmpeg -y "${inputs[@]}" -filter_complex "$filter" -map "[outv]" \
  -r 30 -c:v libx264 -preset medium -crf 20 "$WORK/$NAME-1080p.mp4" 2>/dev/null

rm -f "$WORK"/slide-*.png "$WORK"/check-*.png "$WORK"/concat.txt "$WORK/$NAME.pdf"
echo "完成: $WORK/$NAME-1080p.mp4"
