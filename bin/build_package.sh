#!/usr/bin/env bash
#
# 打包本专家为可上传的 zip 包。
#
# 用法:
#   bin/build_package.sh [输出zip路径]      # 默认 dist/tripweaver.zip
#
# 约定（与已入库的 dist/tripweaver.zip 保持一致）:
#   - 包内根目录为 tripweaver/，解压后即可作为专家目录使用
#   - 排除版本控制、本地数据、生成产物：.git .gitignore dist output .workbuddy __pycache__ *.pyc *.DS_Store *.log
#   - 打包前校验必需文件齐全，缺失即失败（避免再出现「包落后于源码」）
#   - 打包后 unzip -t 校验完整性，文件按字典序写入（同内容产出同顺序）
set -euo pipefail

PKG_NAME="tripweaver"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist/$PKG_NAME.zip}"

# 不入包的内容
EXCLUDES=(
  ".git" ".gitignore" "dist" "output" ".workbuddy" ".idea" ".jura"
  # docs/ 是专家中心的运营素材（样张/文案），不随运行包分发
  "docs"
  "__pycache__" "*.pyc" "*.pyo" ".DS_Store" "*.log"
)

# 包内必须存在的文件；缺任何一项说明打包源不完整
REQUIRED=(
  "$PKG_NAME/.codebuddy-plugin/plugin.json"
  "$PKG_NAME/README.md"
  "$PKG_NAME/agents/travel-planner.md"
  "$PKG_NAME/bin/generate_travel.py"
  "$PKG_NAME/bin/generate_share.py"
  "$PKG_NAME/bin/generate_checklist.py"
  "$PKG_NAME/bin/generate_weather.py"
  "$PKG_NAME/bin/coord_convert.py"
  "$PKG_NAME/references/itinerary-schema.md"
  "$PKG_NAME/references/share-guide.md"
  "$PKG_NAME/references/checklist-guide.md"
  "$PKG_NAME/references/weather-guide.md"
  "$PKG_NAME/references/coordinate-sources.md"
  "$PKG_NAME/references/poi-coords.json"
  "$PKG_NAME/avatars/expert.png"
)

for c in rsync zip unzip; do
  command -v "$c" >/dev/null || { echo "缺少命令: $c" >&2; exit 1; }
done

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rsync -a "${EXCLUDES[@]/#/--exclude=}" "$ROOT/" "$STAGE/$PKG_NAME/"

missing=0
for f in "${REQUIRED[@]}"; do
  if [[ ! -f "$STAGE/$f" ]]; then
    echo "❌ 缺少必需文件: $f" >&2
    missing=1
  fi
done
[[ $missing -eq 0 ]] || { echo "打包中止：请先补齐上述文件。" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
( cd "$STAGE" && find "$PKG_NAME" -type f | LC_ALL=C sort | zip -q -X "$OUT" -@ )

unzip -tq "$OUT" >/dev/null || { echo "❌ 包完整性校验失败: $OUT" >&2; exit 1; }

echo "✅ 打包完成: $OUT"
echo "   根目录 : $PKG_NAME/"
echo "   文件数 : $(unzip -Z1 "$OUT" | wc -l | tr -d ' ')"
echo "   大小   : $(du -h "$OUT" | cut -f1)"
