---
name: docker-compose-port-conflict-triage
description: 诊断并修复「docker compose up 在启动阶段失败 / 报 Bind for 0.0.0.0:xxxx failed: port is already allocated / 端口已被占用 / 容器起不来」。当用户贴上 CI 或本机的 `up -d` 失败日志、说「端口被占了」「容器启动失败」「Bind failed」「Starting 阶段报错」「上次还好好的这次就不行了」「日志里 Recreated 了但没起来」「两套编排互相抢端口」「部署到一半挂掉」，或需要给流水线加一道「起容器前先查端口占用」的前置守卫时使用。覆盖四类高频误判——把 `Recreate → Recreated` 读成启动成功、只看 `ss` 监听导致把自有容器误判为冲突、compose 在第一个服务失败即中止导致看不到其余端口、失败后无自动回滚导致下一次 up 仍打印一串 Recreated；并给出「自有容器 / 外部容器 / 宿主进程」三分类的判别方法与可直接复用的 preflight 脚本骨架。
agent_created: true
---

# docker compose 端口占用：为什么「上次还好好的」

## 核心原则

**这条报错 99% 与镜像、配置、代码无关。** 看到 `port is already allocated` 就不要去重建镜像、
不要怀疑 `.env`、不要 `down -v` —— 只有一个问题：**那个宿主端口此刻被别人占着。**

先记住 compose 的三个"沉默行为"，它们让现场极具误导性：

| # | compose 的行为 | 后果（误判） |
|---|---|---|
| 1 | 端口绑定发生在 **`Starting`** 阶段，不在 `Recreated` | 看到 `Recreate → Recreated` 就以为成了 |
| 2 | 第一个服务启动失败即**中止** | 后面几个端口是否也冲突**根本看不到** |
| 3 | 失败后**不自动回滚**；`restart` 策略也不会在失败时生效 | 节点上留下 Created/Exited 容器，下一次 `up` 照样先刷一串 `Recreated` |

🔴 **判据：日志里出现「有的容器 `Running`、有的容器在 `Starting` 时炸」的混合形态** ——
这不是随机故障，而是"只有部分端口冲突"的典型指纹（不发布宿主端口的服务天然不冲突）。

## 第一步：先问「谁占的」，别急着修

```bash
# ① 容器维度（带 compose 项目标签，区分是哪个编排）
docker ps --filter publish=9999 \
  --format '{{.Names}}{{"\t"}}{{.Label "com.docker.compose.project"}}{{"\t"}}{{.Label "com.docker.compose.service"}}'

# ② 宿主进程维度（排除 docker-proxy —— 它只是容器的端口代理，不是真占用者）
ss -lptnH                      | awk -v P=9999 '{n=split($4,a,":"); if(a[n]==P) print}'   # Linux
lsof -nP -iTCP:9999 -sTCP:LISTEN                                                          # macOS
```

`com.docker.compose.project` 标签为**空** ⇒ 那是 `docker run` 手工创建的容器，
**compose 完全管不到它**，是最隐蔽的占用来源。

## 第二步：三分类，只有一类是真冲突

| 占用者 | 判据 | 处置 |
|---|---|---|
| **自有容器** | `project` 标签 == 本次要 up 的编排的 project | ✅ **不是冲突**。compose 走 Recreate 会先 stop+rm 释放端口 |
| **外部容器** | `project` 标签 ≠ 本编排（或为空） | 🔴 真冲突。停掉它，或改用 `HOST_*_PORT` 错开 |
| **宿主进程** | `docker ps` 无命中，但 `ss`/`lsof` 有监听 | 🔴 真冲突。`kill <pid>` 或让出端口 |

🔴 **只跑 `ss` 会把自有容器全判成冲突（全员假报警）** —— 必须先用 `docker ps --filter publish=`
判一次归属，再决定要不要看宿主进程。

## 第三步：把「要占哪些端口」从编排里算出来，别手抄

手抄端口会漏掉 profile 里的服务。正确姿势是用 compose 自己解析（env 与 profile 都会被代入）：

```bash
docker compose --profile <p> --env-file a.env --env-file b.env -f x.yml \
  config --format json | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("project =", d.get("name"))
for svc,s in (d.get("services") or {}).items():
    for p in (s.get("ports") or []):
        if p.get("published"):
            print(f'"'"'{p["published"]:>6}  {svc:16} {s.get("container_name","")}'"'"')
'
```

要点：
- `config --format json` 的顶层 **`name`** 就是要比对归属的 project 名（`name:` 字段或目录名）；
- **必须带 `--profile`**，否则 `profiles: [pcui]` 之类的服务不会出现在结果里，8890 这类端口会被漏检；
- **必须带全部 `--env-file`**，否则 `${HOST_*_PORT:-默认}` 会退回默认值，算出的端口是错的；
- 退化路径：JSON 是 pretty-print 的，`grep -o '"published"[[:space:]]*:[[:space:]]*"[0-9]*"'` 也能抽。

## 第四步：把守卫装进流水线（一劳永逸）

在 `up -d` **之前**跑一次 preflight，把 daemon 的原始报错换成「谁占的 + 怎么办」，
并且**不浪费一次十几分钟的构建**。骨架见本技能 `assets/preflight_ports.sh`，关键设计：

1. 端口表用 `docker compose config` 推导（见第三步），解析失败退到内置默认表；
2. 逐端口三分类（见第二步），**自有容器不算失败**（否则天天假报警）；
3. 额外做一条「**两套编排是否同时在跑**」的整体判据 —— 多编排仓库里这是最高频的根因；
4. 占用时**直接打印可复制的处置命令**，而不是让人再去搜；
5. 退出码：`0` 可继续 / `1` 有外部占用 / `2` 环境问题，便于流水线直接 `set -e` 用。

## 常见根因清单（按频率）

| # | 根因 | 特征 |
|---|---|---|
| 1 | **同一仓库的多套编排同时在跑，宿主端口重叠** | 仓库文档里通常已经写着"不要同时启动"；两侧 project 名不同但端口相同 |
| 2 | **仓库从"共用一份数据/网络"演进出借用关系** | 比如 A 编排经 external 网络借用 B 编排的 mysql ⇒ 停 B 时**必须保留那个服务**，`down` 整个 B 会连带把依赖停掉 |
| 3 | 手工 `docker run` 的容器（无 project 标签） | 历史遗留，compose 管不到 |
| 4 | 别的项目 / 系统服务 / 常见端口撞车 | 9999、8080 这类端口尤其容易被无关进程占 |
| 5 | 并发构建 | Jenkins 缺 `disableConcurrentBuilds()` 时两个同 job 构建互抢；固定 `container_name` 会先撞「名字已存在」，端口冲突是它的变体 |

## 处置时的三条红线

1. **不要用 `down -v` 来"清干净"** —— 那会删数据卷。端口冲突跟数据卷毫无关系。
2. **不要为了错开端口而改 compose 里的容器间地址** —— 容器互访用的是服务名 + 容器内端口，
   改宿主映射就够了；但要注意**前端 nginx 的 upstream 与宿主端口无关**，改了反而看不懂。
3. **停掉一套编排之前，先确认没有 `external` 网络的借用依赖** ——
   （`docker compose -f B.yml down` 会把 B 全部服务停掉，而 A 可能正连着 B 的某个服务）。

## 回复用户时的措辞要点

- 明确说「**这不是镜像/配置/代码问题**」，否则用户会去重建镜像浪费一轮；
- 给出**一句能在目标机上定案的命令**（`--who <port>`），而不是让用户自己猜；
- 说明**为什么日志看着像"上次是好的"**（`Recreated` / `Running` 的误导性）——
  这是这类故障最容易被误读的地方，讲清楚用户下次自己就能判。
