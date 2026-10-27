---
name: contact-manager
description: 联系人管理智能体：每天拉取飞书新消息（私聊全部+群@我），对消息分类、对联系人分类，提炼「今日必做」清单并推送到用户飞书私信。触发词：今日消息 / 消息分类 / 今日必做 / 早报 / 谁找过我…
agent_created: true
---

# 联系人管理智能体（contact-manager）

每天 8:30 早报：谁找过我 → 消息分了什么类 → 今天必须做什么。

## 采集（脚本完成）

```bash
/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
  ~/.workbuddy/skills/contact-manager/scripts/collect_messages.py \
  --output "/Users/shan/WorkBuddy/日常工作/digests/<YYYY-MM-DD>-messages.json"
```

- 默认窗口：昨天 18:00 → 现在；自动翻页全会话；机器人/系统助手黑名单已内置
- 群消息只保留 @阿钰/@李映钰/@_all 的；私聊全量（含自己发出的，标记 `self:true`）
- 我的身份：李映钰 `ou_a56cc3f1bc5d7da81b5595016b53aff3`

## 分类规则

**消息分类**（每条打一个标签）：
| 类别 | 判定 |
|---|---|
| 需要我行动 | 私聊他人发来、含请求/提问/指令/求助语义（排除寒暄） |
| 时间约定 | 含会议/评审/具体时间点（今天或未来的） |
| 信息知会 | 文档链接、进度同步、通知转发，无需回复 |
| 闲聊其他 | 表情、寒暄、无行动点 |

**联系人分类**（按会话聚合）：
| 类别 | 判定 |
|---|---|
| 待我回复 | 会话里有「需要我行动」且我尚未回复（我方最后一条非确认语） |
| 今日活跃 | 今天有往来但已闭环 |
| 系统/自动化 | 项目管理系统卡片、机器人通知 |

**今日必做**（按优先级排）：
1. 私聊明确指派/请求且含今天或截止时间
2. 群 @我/@_all 布置的事项
3. 系统提醒卡点名的欠账（如「未完成任务提醒」）
4. 有时间约定的会议/评审（附时间）
没有则明确说「今日无必做事项」，不许编造。

## 推送（写报告 + 发私信）

1. 完整报告写 `~/WorkBuddy/日常工作/digests/<YYYY-MM-DD>-report.md`（消息分类明细 + 联系人分类 + 必做清单）
2. 简版推给自己（**必须 bot 身份，user 身份缺 im:message.send_as_user**）：

```bash
lark-cli im +messages-send --user-id ou_a56cc3f1bc5d7da81b5595016b53aff3 \
  --msg-type text --content '{"text":"<简版必做清单>"}' --as bot
```

⚠️ `--msg-type` 不支持 `markdown`（2026-10-19 实测报 validation 错误，允许值：text/post/interactive…），用 `text` + `\n` 换行即可。

简版结构：`📬 今日必做（N 件）` → 每件一行（事项 + 来源人/群 + 时间）；`💬 待回复`；无必做则一句话说明。文本放 JSON `text` 字段，控制 4000 字以内。

## 硬性约束

- 只读消息 + 只给自己发私信，**绝不**代回复任何联系人、不动任何群
- 消息内容属于隐私，报告只存本地 digests/ 目录
- 拉取失败/0 条消息时如实汇报，不虚构
