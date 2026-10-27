---
name: junk-file-cleaner
description: 扫描 macOS 上开发构建产物垃圾文件（node_modules/dist/.venv/__pycache__ 等）并安全清理（一律移入废纸篓，可还原）。当用户说「清理垃圾文件」「扫一下垃圾」「磁盘空间不够」「清理构建产物」时使用。
agent_created: true
---

# Junk File Cleaner — 垃圾文件扫描与安全清理

## 铁律
1. **只扫描不删除**：扫描只出报告，删除必须等用户明确确认（确认哪一项/哪些项）。
2. **白名单机制**：只认脚本内 `TARGET_DIRS/TARGET_FILES` 名录里的构建产物，其他一律拒绝清理（防误删）。
3. **删除只走废纸篓**：`/usr/bin/trash`（已验证沙箱可用；osascript 走 Finder 会被沙箱 -10004 拦，不要用）。
4. **运行时排除**：路径含 `docker/volumes/`、`plugin_daemon`、`/venvs/` 的是运行时依赖（如 Dify 插件环境），自动跳过不报——删了会弄坏服务。

## 用法
```bash
PY=/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
SCRIPT=/Users/shan/.workbuddy/skills/junk-file-cleaner/scripts/scan_junk.py

# 扫描 + 出报告（默认根目录：WorkBuddy/Claude/my-strapi-project/dify/ai-secretary/jenkins-agent）
$PY $SCRIPT --report "/Users/shan/WorkBuddy/日常工作/junk-reports/$(date +%F).md"

# 确认后清理（可多项，全部移入废纸篓）
$PY $SCRIPT --trash /path/to/node_modules /path/to/dist
```

## 参数
- `--roots`：逗号分隔的扫描根目录，可自定义
- `--min-size-mb`：报告阈值，默认 1MB
- `--report` / `--json`：输出 Markdown / JSON 报告
- `--trash <path...>`：把指定构建产物移入废纸篓（白名单校验）

## 配套自动化
「垃圾文件每日扫描报告」：每天 09:30 自动扫描出报告（只报告不删除），删除等用户在会话里确认。
