# skill-sync: 跨设备同步 WorkBuddy 用户级技能（git 底座，Windows 版）
# 用法: powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.workbuddy\skills\skill-sync\scripts\sync.ps1"
$ErrorActionPreference = "Stop"
$SkillsDir = Join-Path $env:USERPROFILE ".workbuddy\skills"
$Remote = if ($env:SKILLS_REMOTE) { $env:SKILLS_REMOTE } else { "origin" }
$Branch = if ($env:SKILLS_BRANCH) { $env:SKILLS_BRANCH } else { "main" }

Set-Location $SkillsDir

# --- 前置检查 -------------------------------------------------------------
if (-not (Test-Path (Join-Path $SkillsDir ".git"))) {
    Write-Output "RESULT: ERROR"
    Write-Output "REASON: $SkillsDir 不是 git 仓库。新设备请先按 skill-sync/SKILL.md 的「新设备首次接入」操作。"
    exit 2
}
$remoteUrl = git remote get-url $Remote 2>$null
if (-not $remoteUrl) {
    Write-Output "RESULT: ERROR"
    Write-Output "REASON: 未配置远端 $Remote。请执行: git remote add origin <私有仓库地址>"
    exit 2
}

# --- 1. 拉取远端 ----------------------------------------------------------
$Before = git rev-parse HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or -not $Before) { $Before = "none" }
git fetch $Remote $Branch --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Output "RESULT: ERROR"
    Write-Output "REASON: git fetch 失败（网络不可达 / 凭据失效）。检查网络或重新 gh auth login。"
    exit 1
}
$Incoming = git rev-list --count "HEAD..$Remote/$Branch" 2>$null
if ($LASTEXITCODE -ne 0) { $Incoming = "?" }

if ($Incoming -ne 0 -and $Incoming -ne "?") {
    git rebase --autostash "$Remote/$Branch" 2>$null
    if ($LASTEXITCODE -ne 0) {
        git rebase --abort 2>$null
        Write-Output "RESULT: CONFLICT"
        Write-Output "REASON: 本地与远端改动冲突，rebase 已安全回退（本地未动）。"
        Write-Output "修复: 手动 git pull --rebase origin main 解决冲突后重跑本脚本。"
        exit 1
    }
}

# --- 2. 本地变更 → 提交并推送 ---------------------------------------------
$status = git status --porcelain
if ($status) {
    git add -A
    $hostName = $env:COMPUTERNAME
    $date = Get-Date -Format "yyyy-MM-dd"
    git commit -m "sync: skills update from $hostName $date" --quiet
    git push $Remote $Branch --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Output "RESULT: ERROR"
        Write-Output "REASON: git push 失败（网络 / 凭据 / 远端又有新提交）。可重跑一次本脚本。"
        exit 1
    }
    $Pushed = (git diff --name-only "$Before" HEAD -- | Measure-Object -Line).Lines
} else {
    $Pushed = 0
}

# --- 3. 摘要 --------------------------------------------------------------
Write-Output "RESULT: OK"
Write-Output "PULLED: $Incoming 个远端提交"
Write-Output "PUSHED: $Pushed 个本地文件变更"
$skillCount = (Get-ChildItem $SkillsDir -Directory | Where-Object { $_.Name -ne ".git" }).Count
Write-Output "SKILLS: $skillCount 个技能目录"
