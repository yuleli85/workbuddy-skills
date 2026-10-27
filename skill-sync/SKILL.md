---
name: skill-sync
description: >-
  跨设备同步 WorkBuddy 用户级技能。同一账户在多台电脑（macOS / Windows）登录时，把其它电脑上安装或修改的
  技能同步到本机，并把本机新增/修改的技能推回去。底层是托管在 GitHub 私有仓库的 git 同步
  （~/.workbuddy/skills 本身就是 git 仓库，node_modules 等依赖不入库）。触发词：同步技能、技能同步、
  skill sync、同步其它电脑的技能、拉取技能、推送技能。
agent_created: true
---

# skill-sync — 跨设备技能同步

`~/.workbuddy/skills/` 是 git 仓库，远端为 GitHub 私有仓库。WorkBuddy 对技能是纯目录扫描，
**文件同步到位后重启会话即生效**，无需注册。

## 日常使用（对 WorkBuddy 说「同步技能」即触发本技能）

```bash
# macOS / Linux
bash ~/.workbuddy/skills/skill-sync/scripts/sync.sh
# Windows
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.workbuddy\skills\skill-sync\scripts\sync.ps1"
```

脚本逻辑：fetch → 有远端新提交则 `rebase --autostash` → 本地有变更则自动 commit（消息含主机名+日期）并 push。
三种结果：`RESULT: OK` / `RESULT: CONFLICT`（已安全回退，需手动解决）/ `RESULT: ERROR`（网络/凭据问题）。

## 新设备首次接入

前提：已装 git；已 `gh auth login`（或配置了 GitHub 凭据）；已设置
`git config --global user.name` / `user.email`。

**情况 A：本机 `~/.workbuddy/skills` 尚无任何自装技能（推荐）**

```bash
mv ~/.workbuddy/skills ~/.workbuddy/skills.bak.$(date +%s)   # Windows: Rename-Item
git clone git@github.com:<你>/workbuddy-skills.git ~/.workbuddy/skills
# 从备份里找回 _bm_skillid_migration.json（每台机器各自的迁移记录，不入库）
cp ~/.workbuddy/skills.bak.*/_bm_skillid_migration.json ~/.workbuddy/skills/ 2>/dev/null || true
```

**情况 B：本机已有技能目录，要并入同步**

```bash
cd ~/.workbuddy/skills
git init -b main
git remote add origin git@github.com:<你>/workbuddy-skills.git
git fetch origin main
git reset --hard origin/main          # ⚠️ 会用远端版覆盖本地同名技能；本机独有技能先备份出去
git add -A && git commit -m "sync: merge local skills from <hostname>"
git push origin main
```

## 约定与注意

- **不同步的**：`node_modules/`、`__pycache__/`、`.venv/`、`dist/`、`.DS_Store`、
  `_bm_skillid_migration.json`（见仓库根 `.gitignore`）。zh-ppt / web-autotest 等带依赖的技能，
  在新机器上首次使用前需在其目录内 `npm install`。
- **项目级技能**（`{workspace}/.workbuddy/skills/`）不入本仓库，随各项目自己的 git 走。
- **安全**：新技能入库前自查密钥/token（参照 repo-credential-remediation 的口径），
  真实凭据一律用 `<PLACEHOLDER>` 占位并注明真实值获取处。远端必须是**私有**仓库。
- **冲突**：两台电脑同时改同一技能时 rebase 会安全回退，手动 `git pull --rebase origin main`
  解决后重跑同步脚本即可。
- 每台机器的 WorkBuddy 每日自动化会各自跑一次同步（见自动任务「技能跨设备同步」）。
