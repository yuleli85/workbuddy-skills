---
name: daily-agent-digest-add-source
description: 给 daily-agent-digest（本地 AI agent 会话日报）新增/修复一个采集来源，或回答「某个 AI 编程 agent 的会话存在本地哪里、什么格式」。当用户说「日报只监控了 X,想加 Y」「增加采集来源」「某 agent 的会话记录在哪」「日报里没有 X 的工作」「采集器读不到数据」时使用。内含 20+ agent 的本地会话落盘路径/格式清单、注册表式加采集器的标准步骤（抽取器 + 采集器 + 注册表 + 夹具 + 测试）、以及"装了但读不到"必须显式上报的规则。
agent_created: true
---

# 给日报加一个 agent 采集来源

**仓库**：`/Users/shan/work/daily-agent-digest`（引擎 `daily_agent_digest.py`，单文件 ~1000 行）。

**目标**：新增来源后，当天日报真的能读到它的工作内容；读不到的来源**显式说明**，绝不静默。

## 核心原则

1. **先验证落盘，再写代码**。不要按文档猜格式：在真机上 `ls`/`sqlite3` 打开一次，确认路径与字段名。猜出来的解析器 = 永远返回 0 条。
2. **宁可漏，不可错**。认不出的形状返回 `(None, None)` 丢弃，绝不用关键词/正则去"捞"文本。
3. **两种情况必须分开**：机器上**没用过**该 agent（静默跳过）vs **装了但本工具读不到**（写成 `stats['unsupported']`，会汇成一行「未覆盖的来源」进 warnings）。
4. **先抽取、后截断**。任何"先截 4000 字符再解析 JSON"都会拿到半个 JSON。
5. **不是所有东西都有本地会话**。桌面客户端（豆包、千问 App、Trae 新版）常常只存 IndexedDB 或云端加密 —— 这种情况的正确答案是"采不到 + 说明原因"，不是硬做。

## agent 本地会话落盘清单（macOS，已实测/公开记录）

| Agent | 路径 | 格式要点 |
| --- | --- | --- |
| Codex（老） | `~/.codex/thread_history*.sqlite` | 表 `thread_items(thread_id, turn_id, created_at_ms, item_json, item_type)`；`userMessage`/`agentMessage` 才是正文。**2026-09 之后这个库不再增长** |
| Codex（新） | `~/.codex/sessions/<年>/<月>/<日>/rollout-*.jsonl` | 一行一事件。`response_item` + `payload.type=message` + `payload.role=user\|assistant`，正文在 `payload.content[].input_text\|output_text`；`event_msg` + `payload.type=task_complete` 的 `last_agent_message` 是最终答复；`role=developer` 是注入上下文 |
| Claude Code | `~/.claude/projects/<项目连字符编码>/<会话 uuid>.jsonl` | `type=user\|assistant`，正文 `message.content`（字符串或分片）；`thinking`/`tool_use`/`tool_result` 全丢；`isSidechain=true` 是子代理轨迹，跳过 |
| WorkBuddy / CodeBuddy | `~/.workbuddy/projects/<项目>/<会话 uuid>.jsonl` | `type=message` + 顶层 `role=user\|assistant`，分片是 **`input_text`/`output_text`**（不是 `text`）；`timestamp` 是**毫秒** |
| pi | `~/.pi/agent/sessions/**/*.jsonl` | `type=message` + `message.role` + `content[].text` |
| DeepSeek Harness | `~/.dsh/sessions/<sid>/*.zstd` | zstd 压缩的 JSONL；`user/message`/`assistant/message`/`deliverables/presented`。**macOS 不自带 zstd** |
| Qwen Code（千问 CLI） | `~/.qwen/projects/<项目>/chats/*.jsonl`；旧版 `~/.qwen/tmp/<hash>/{chats/*.json,logs.json}` | gemini-cli 形状：`message.parts[].text`，`thought: true` 是思考；`logs.json` 是**整文件 JSON 数组** |
| Trae | `~/Library/Application Support/{Trae,Trae CN,TRAE SOLO CN}/User/workspaceStorage/<工作区>/{chatSessions/*,state.vscdb}` | 编辑器侧是 Copilot 形状 `requests[].message.text` / `requests[].response[].value`；旧版把会话内联在 `state.vscdb`。**新版加密/在云端 → 读不到** |
| Qoder | `~/Library/Application Support/Qoder/SharedClientCache/cli/projects/*.session.execution.jsonl`（**平铺目录**，不按项目分）+ `.../User/workspaceStorage/<工作区>/chatSessions/*` | 前者是 `{role, parts:[{text}]}`；`~/.qoder/projects/` 通常是空的 |
| 豆包（桌面端） | `~/Library/Application Support/Doubao/Default/IndexedDB/chrome_doubao-chat_*` | **只有 IndexedDB，取不出正文 → 采不到** |
| 千问（桌面端 App） | 无本地会话目录 | **采不到**；只有 Qwen Code CLI 有 |
| Cursor | CLI `~/.cursor/projects/*/agent-transcripts/*.jsonl`；IDE `Cursor/User/{globalStorage,workspaceStorage/*}/state.vscdb` | SQLite 键值 / JSONL |
| VS Code Copilot | `Code/User/workspaceStorage/*/chatSessions/*.json(l)` | `requests[]` 形状 |
| Kimi | `~/.kimi-code/sessions/.../wire.jsonl`、`User/Library/Application Support/kimi-desktop/.../sessions/` | JSONL |
| opencode | `~/.local/share/opencode/opencode.db` | SQLite |

**通用判据**：`<工具>/projects/<项目>/<会话>.jsonl` 是 CodeBuddy 系（Claude Code / WorkBuddy / Cherry Studio）的家族特征；VS Code 系（Cursor / Trae / Qoder / Copilot / Windsurf）都用 `User/workspaceStorage/*/state.vscdb`。

## 加一个采集器的步骤

1. **探针验证**（必做，一步都别省）：
   ```bash
   ls -d ~/.<tool> ~/Library/Application\ Support/<Tool> 2>/dev/null
   # 打开一条记录看真实字段名 + 时间戳单位
   /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 - <<'PY'
   import json,glob,os,collections
   f=sorted(glob.glob(os.path.expanduser('~/.<tool>/**/*.jsonl'),recursive=True))[0]
   for i,line in enumerate(open(f,errors='replace')):
       o=json.loads(line); print(o.get('type'), sorted(o.keys()))
       if i>4: break
   PY
   ```
2. **写抽取器** `extract_<name>(obj) -> (role, text)`，`role ∈ {prompt, result, deliverable, None}`。
   分片正文优先复用 `parts_text_any`（认 `text`/`input_text`/`output_text`），结尾套 `strip_agent_noise` 去注入标签。
3. **写采集器** `def <name>(root, start, end):` —— 签名固定，返回 `(dedupe(out), stats)`。
   文件枚举一律走 `_glob(base, pattern, since=start)`（`since` 按 mtime 预筛，不加会慢 10 倍）。
4. **注册**：在 `COLLECTORS` 元组加一行 `(名字, 函数, '会话位置说明')`。`collect()` 会自动隔离异常。
5. **读不到就说**：形如
   ```python
   if <profile 存在> and not harvested:
       stats['unsupported'] = '<为什么读不到>'
   ```
   `collect_warnings` 会把所有 `unsupported` 合成一行「未覆盖的来源」。**不要**用 warnings 报"没用过"。
6. **夹具 + 测试**（缺一不可，否则等于没接）：
   - `scripts/dev_fixtures.py`：按真实形状写入夹具；**同时写入一个"装了但读不到"的来源**。
   - `tests/test_core.py`：加端到端断言（`engine.collect(source, *engine.day_window(day))` 后核 `role` 列表），
     以及一条 `unsupported → warnings` 的断言。
7. **验证**：
   ```bash
   cd /Users/shan/work/daily-agent-digest
   /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m unittest discover -s tests
   ./scripts/dev.sh generate            # 离线端到端(mock LLM)
   # 真实主目录、单日、看每个来源的 kept 数
   echo '{"date":"YYYY-MM-DD"}' | DIGEST_HOME=/tmp/chk \
     /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 daily_agent_digest.py --app-command generate > /tmp/chk.json
   ```

## 踩过的坑

- **本机 PATH 上的 `grep` 是 brokered shim,不支持 `\|`**（会静默无匹配 ⇒ 假报"没落地"）。用 Grep 工具或 `grep -E 'a|b'`。
- WorkBuddy/CodeBuddy 的分片名是 `input_text`/`output_text`，只认 `text` 的 `parts_text` 会一条都取不到。
- codex 换了存储世代（sqlite → `sessions/**/rollout-*.jsonl`），修复采集器前先看 `min/max(created_at_ms)`，别被"库还在但没数据"骗了。
- agent 会把 `<system-reminder>` / `<INSTRUCTIONS>` / `# AGENTS.md instructions` 塞进用户消息，不剥离就会变成日报里的"用户需求"。
- `state.vscdb` 里可能有几十 MB 的模型清单缓存，解码前先看 blob 长度（见 `VS_CODE_VALUE_MAX`）。
- 性能红线：一次真实采集应 < 1s。变慢先怀疑漏了 `since=start`。
