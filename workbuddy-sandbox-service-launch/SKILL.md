---
name: workbuddy-sandbox-service-launch
description: 在 WorkBuddy(macOS) 会话内启动本地开发服务(FastAPI/uvicorn、Vite/npm dev、Node 服务等)并验证局域网 IP 可达；也用于排查「服务在 WorkBuddy 里跑就出问题、在用户终端跑就正常」这类沙箱差异。当用户说「用 IP 启动服务」「起一下前后端」「服务起不来」「本地服务启动报 PermissionError EEXIST」「nohup 起了但进程没了」「某功能只在 WorkBuddy 里空白/失败」「LibreOffice/soffice 转换失败」「DeploymentException」时使用。覆盖三类隐蔽坑：沙箱 mkdir shim 误报 EEXIST、Bash 后台进程被调用返回时清理、服务进程调原生程序因写不了宿主路径而静默失败。
agent_created: true
---

# 在 WorkBuddy 沙箱内启动并验证本地服务

## 适用场景

- 用户要求「用 IP 启动服务」「起一下前后端」「把项目跑起来」，需要从 WorkBuddy 会话里把常驻 HTTP 服务拉起来并让局域网访问。
- **功能只在 WorkBuddy 会话里失败、在用户自己终端里正常** —— 典型沙箱差异，本 skill 的「场景 B」专门处理。

## 核心结论（先看这个）

在 WorkBuddy 会话内启动/运行服务，有三类必然踩到的坑，表现都像「起不来 / 功能坏」，根因完全不同：

| 现象 | 根因 | 解法 |
|---|---|---|
| 启动即崩，`PermissionError: EEXIST: file already exists, mkdir '...'` | 沙箱 fs shim 对已存在目录的 `mkdir(exist_ok=True)` 未实现 `exist_ok` 语义 | 代码改 `mkdir(parents=True, exist_ok=True)` |
| 启动看似成功（Vite 打印 ready），稍后端口空了、curl 502 | Bash 调用返回时，该调用用 `nohup ... &` 派生的进程被清理 | 改用 Bash 工具 `run_in_background: true` |
| 某功能静默产出错误结果（空白图 / 空数据），日志只有一行 warning | 服务进程调用的**原生程序**要写沙箱外的宿主路径（profile/缓存），被拦后程序自己报错退出 | 把该程序的数据目录重定向到**项目内**；并让错误透传到前端 |

## 执行流程

### Step 1 — 先探测现状，别急着启动

```bash
for IF in en0 en1 en2 en3; do ipconfig getifaddr "$IF" 2>/dev/null; done   # 常是 en1 有 IP,en0 空
lsof -nP -iTCP:8000 -sTCP:LISTEN       # 端口占用(macOS 无 ss,必须用 lsof)
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

服务可能已经在跑 —— 先 `curl` 确认，不要盲目重启（内存态任务会丢）。

### Step 2 — 启动用 `run_in_background: true`

```
Bash(command: "cd <proj> && exec <启动命令>", run_in_background: true)
```

**不要用 `nohup ... &`** —— 调用一返回进程就被清理（后端日志会停在 `Process SpawnProcess-1:` 且无 traceback）。
`run_in_background` 启动的任务才在会话内持续存活。

注意：`run_in_background` 的任务**不继承**非沙箱权限。需要非沙箱的能力（读 `~/.ssh`、git+ssh、系统级安装）必须走**前台 + `dangerouslyDisableSandbox`**。

### Step 3 — 排查「进程消失」

- **被杀**：日志突然截断、无 traceback
- **自己崩**：有完整 traceback

前者 → 是 Step 2 的机制问题（用了 nohup）。uvicorn `--reload` 的 reloader 残留会占端口，重启前清理：

```bash
pkill -f "uvicorn main:app"
```

### Step 4 — 验证（必须用 IP，不能用 localhost）

```bash
IP=$(ipconfig getifaddr en1 || ipconfig getifaddr en0)
curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 8 http://$IP:8000/docs
curl -s http://$IP:8000/api/health
lsof -nP -iTCP:8000 -sTCP:LISTEN | awk 'NR>1{print $1, $2}'
```

**502 是 WorkBuddy 代理返回的「本地无服务」信号**，不是后端业务错误 —— 见 502 就查端口监听，别查业务日志。

---

## 场景 A：沙箱 mkdir shim 的 EEXIST

若服务启动崩在 `mkdir`，先判断写法：

```bash
cd <proj>
./venv/bin/python - <<'PY'
from pathlib import Path
p = Path("uploads")   # 换成报错的那个目录
print("is_dir:", p.is_dir())
for label, fn in [
    ("mkdir(exist_ok=True)",               lambda: p.mkdir(exist_ok=True)),
    ("mkdir(parents=True, exist_ok=True)", lambda: p.mkdir(parents=True, exist_ok=True)),
]:
    try:
        fn(); print(f"  [OK]   {label}")
    except Exception as e:
        print(f"  [FAIL] {label} -> {type(e).__name__}: {e}")
PY
```

**实测判定表**：

| 写法 | 已存在目录 | 新目录 |
|---|---|---|
| `mkdir(exist_ok=True)` | ❌ EEXIST | ✅ |
| `mkdir(parents=True, exist_ok=True)` | ✅ | ✅ |

**修复**：全局把 `.mkdir(exist_ok=True)` 补成 `.mkdir(parents=True, exist_ok=True)`（语义等价、零副作用）。

查残留（用 Grep 工具，别用 bash grep）：
```
Grep(pattern: "\\.mkdir\\(exist_ok=True\\)", glob: "!venv/**", output_mode: "content")
```
逐文件 `Edit(replace_all: true)`。匹配子串 `.mkdir(exist_ok=True)` 不会误伤已带 `parents=True` 的写法。
改完必须 `python -m py_compile <文件...>` 校验。

---

## 场景 B：服务进程调用原生程序静默失败

**症状**：某个功能只在 WorkBuddy 里产出错误结果（如 PPT 转图片全是空白占位图），
用户终端跑同样代码却正常。日志里只有一行 `[模块] xxx 失败: <stderr>`，异常被 catch 掉。

**典型案例**：LibreOffice（soffice）转 PPTX→PDF 时，
默认用户 profile 在 `~/Library/Application Support/LibreOffice`，
服务进程的沙箱策略**拦住了写该路径**：

```
libc++abi: terminating due to uncaught exception of type
com::sun::star::deployment::DeploymentException
```

### 判定步骤

1. 对比「服务进程」与「Bash 直接调用」的结果差异。
   注意：**Bash 前台 / Bash 后台 / Python subprocess 都会成功**，只有 uvicorn 服务进程失败——
   别被「Bash 里能跑」误导。
2. 找该程序写宿主路径的位置（profile / cache / 临时目录）。
   `HOME`、`PATH`、broker socket 往往都一致，**不是**这些层面的问题。
3. 检查产物是否「静默降级」：占位图/默认值往往有固定的小体积特征
   （例：9,206 B 的灰白占位 PNG vs 真实渲染 120~320 KB）。

### 修复模式

**把该程序的数据目录重定向到项目内**（工作区内的读写沙箱直接放行）：

```python
def _lo_profile_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / ".lo_profile"
    d.mkdir(parents=True, exist_ok=True)
    return d

subprocess.run(
    [soffice,
     f"-env:UserInstallation=file://{lo_profile.as_posix()}",   # 必须在动作参数前
     "--headless", "--convert-to", "pdf",
     "--outdir", str(pdf_dir), str(src.resolve())],
    capture_output=True, text=True, timeout=180,   # 首次建 profile 较慢,给足超时
)
```

同类程序（浏览器 / ffmpeg / 其他 CLI）思路一致：找 `--user-data-dir` / `HOME` / `TMPDIR` / `--cache-dir`
这类开关，统统指到项目内。

### 同时修掉「静默降级」

只修环境不够 —— 失败的**静默降级**才是问题难被发现的根源：

1. 让降级函数返回警告：`-> tuple[list[Path], str]`，成功时 warning 为 `""`
2. 接口响应带上 `render_warning` 之类的字段
3. 前端**有 warning 时用 error toast**，不要无条件报成功（`toast.success('解析完成')` 是反模式）

### 修完别忘了修历史数据

降级产物通常会被缓存（`if len(existing) != expected` 之类的跳过逻辑），
用户旧项目不会自动重导。写个一次性脚本扫「体积小于阈值」的产物重新生成。

---

## 持久化建议

会话内 `run_in_background` 的服务会随会话结束而停止。若用户需要**长期运行**，
交付一键脚本让他在**自己的终端**执行（非沙箱 + 真持久）——这也是场景 B 的天然免疫环境。

脚本要点：
- `lsof` 做端口预检（macOS 无 `ss`）
- 遍历 `en0 en1 en2 en3` 取 IP（`hostname -I` 仅 Linux）
- 用 `if [ -n "$X" ]; then ... fi` 而**不是** `[ -n "$X" ] && ...`
  —— 后者在 `set -e` 下会把脚本直接顶掉
- 支持 `start` / `stop` / `status`，日志落 `logs/*.log`

## 反模式清单

- ❌ 用 `ss -tln` 做端口预检（macOS 没有 `ss`，会静默失效）
- ❌ 用 `hostname -I` 取 IP（Linux 专有）
- ❌ 用 `nohup cmd &` 启动常驻服务（会被清理）
- ❌ 在 `set -e` 脚本里写 `[ -n "$X" ] && cmd`（空值时整个脚本退出）
- ❌ 用 bash 的 `grep 'a\|b'`（本机 grep 是 shim，不支持 BRE 交替，会静默无匹配）
- ❌ 用 `/usr/bin/git`（Xcode 许可门会拦；用 PATH 首位的 `~/.local/bin/git`）
- ❌ 用 `timeout` 命令（macOS 无此命令，GNU coreutils 专有）
- ❌ 依赖「Bash 里跑得通」就断定服务里也跑得通 —— 沙箱上下文不同
