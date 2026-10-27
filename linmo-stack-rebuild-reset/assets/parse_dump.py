#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 mysqldump 全文解析，供「重建 + 重置数据库」的收尾比对使用。

为什么不用 SQL 侧 GROUP_CONCAT + PREPARE 取行数：
  那条写法会**静默截断**（2026-10-13 实测：275 张表只回 161 行），被漏掉的表全被当成
  「现 = 0」⇒ 待补灌表数从 54 虚增到 116，还会诱导你去 DROP 本已存在的表。
  本脚本在宿主侧把 INSERT 的 VALUES 元组按**顶层括号**切分，数量精确。

用法：
  python3 parse_dump.py <all-databases.sql> counts   # 每表行数：pig.* / pig_dw.* / pig_config.*
  python3 parse_dump.py <all-databases.sql> jobs     # sys_job 明细：job_id / status / params / cron / name
  python3 parse_dump.py <all-databases.sql> apps     # ai_app_config 全部行（TSV，列序见 AI_COLS）
  python3 parse_dump.py <all-databases.sql> ddl <db> <table>   # 该表的 CREATE TABLE（带 USE）

要点：
  · mysqldump 的 extended INSERT 可能跨行 ⇒ 必须按语句边界推进，不能按行读。
  · 元组切分要处理：单引号内的逗号/括号、反斜杠转义、嵌套括号。
  · 库上下文切换点 = 形如 "-- Current Database: <名字>" 的注释行，跨库同名表靠它区分。
"""
from __future__ import annotations

import collections
import re
import sys

AI_COLS = [
    'id', 'app_code', 'app_name', 'app_type', 'dify_mode', 'dify_app_id',
    'api_key_cipher', 'dataset_key_cipher', 'base_url', 'model_code', 'tenant_id',
    'enabled', 'sync_source', 'sync_time', 'dify_status', 'dify_updated_at',
    'version', 'remark', 'create_by', 'create_time', 'update_by', 'update_time', 'del_flag',
]
JOB_COLS = [
    'job_id', 'job_name', 'job_group', 'job_order', 'job_type', 'execute_path',
    'class_name', 'method_name', 'method_params_value', 'cron_expression',
    'misfire_policy', 'job_status',
]


def split_tuples(body: str) -> list[str]:
    """按顶层括号切分 VALUES 元组，返回每个元组的原文（含外层括号）。"""
    out: list[str] = []
    depth = 0
    inq = False
    esc = False
    cur = ''
    for ch in body:
        if esc:
            cur += ch
            esc = False
            continue
        if inq:
            if ch == '\\':
                cur += ch
                esc = True
            elif ch == "'":
                cur += ch
                inq = False
            else:
                cur += ch
            continue
        if ch == "'":
            inq = True
            cur += ch
            continue
        if ch == '(':
            depth += 1
            cur += ch
            continue
        if ch == ')':
            depth -= 1
            cur += ch
            if depth == 0:
                out.append(cur)
                cur = ''
            continue
        if depth > 0:
            cur += ch
    return out


def parse_row(t: str) -> list[str]:
    """把一个元组拆成字段列表（剥离外层括号；去引号；NULL 保留为字面 'NULL'）。"""
    inner = t[1:-1]
    fields: list[str] = []
    cur = ''
    inq = False
    esc = False
    depth = 0
    for ch in inner:
        if esc:
            cur += ch
            esc = False
            continue
        if inq:
            if ch == '\\':
                cur += ch
                esc = True
            elif ch == "'":
                inq = False
            else:
                cur += ch
            continue
        if ch == "'":
            inq = True
            continue
        if ch == '(':
            depth += 1
            cur += ch
            continue
        if ch == ')':
            depth -= 1
            cur += ch
            continue
        if ch == ',' and depth == 0:
            fields.append(cur.strip())
            cur = ''
            continue
        cur += ch
    fields.append(cur.strip())
    return fields


def unquote(v: str | None):
    """容器字段 → Python 值；'NULL' 字面量 → None。"""
    return None if v == 'NULL' else v


def iter_inserts(path: str):
    """逐条产出 (db, table, 元组原文列表)。"""
    lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
    cur_db = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r'-- Current Database: `([^`]+)`', line)
        if m:
            cur_db = m.group(1)
            i += 1
            continue
        m = re.match(r'INSERT (?:IGNORE )?INTO `([A-Za-z0-9_]+)`', line)
        if not m:
            i += 1
            continue
        buf = line
        j = i
        while not buf.rstrip().endswith(';'):
            j += 1
            if j >= n:
                break
            buf += '\n' + lines[j]
        k = buf.find('VALUES')
        rows = split_tuples(buf[k + 6:]) if k >= 0 else []
        if rows:
            yield (cur_db or '').strip('`'), m.group(1), rows
        i = j + 1


def _dump(rows_all, cols):
    print(f'总行数={len(rows_all)}')
    for r in rows_all:
        f = dict(zip(cols, r))
        print('\t'.join(f'{k}={unquote(v)}' for k, v in f.items()))


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path, mode = sys.argv[1], sys.argv[2]

    if mode == 'counts':
        counts: collections.Counter = collections.Counter()
        for db, tbl, rows in iter_inserts(path):
            if db in ('pig', 'pig_dw', 'pig_config'):
                counts[(db, tbl)] += len(rows)
        for (db, tbl), c in sorted(counts.items()):
            print(f'{db}.{tbl}\t{c}')
        return 0

    if mode == 'jobs':
        rows_all = []
        for db, tbl, rows in iter_inserts(path):
            if db == 'pig' and tbl == 'sys_job':
                rows_all += [parse_row(r) for r in rows]
        print(f'总行数={len(rows_all)}')
        for r in rows_all:
            f = dict(zip(JOB_COLS, r))
            print(f"{f['job_id']}\t{unquote(f['job_status'])}\t"
                  f"{unquote(f['method_params_value'])}\t{f['cron_expression']}\t{f['job_name']}")
        return 0

    if mode == 'apps':
        rows_all = []
        for db, tbl, rows in iter_inserts(path):
            if db == 'pig' and tbl == 'ai_app_config':
                rows_all += [dict(zip(AI_COLS, parse_row(r))) for r in rows]
        live = [r for r in rows_all if unquote(r.get('del_flag')) == '0']
        sys.stderr.write(
            f'总行数={len(rows_all)} 活行={len(live)} '
            f"enabled=1={sum(1 for r in live if unquote(r['enabled']) == '1')} "
            f"有密钥={sum(1 for r in live if unquote(r['api_key_cipher']))}\n")
        _dump(rows_all, AI_COLS)
        return 0

    if mode == 'ddl':
        db, table = sys.argv[3], sys.argv[4]
        txt = open(path, encoding='utf-8', errors='replace').read()
        m = re.search(r'CREATE TABLE `%s` \((.*?)\n\) ENGINE[^;]*;' % re.escape(table), txt, re.S)
        if not m:
            sys.stderr.write('未找到\n')
            return 1
        print(f'USE `{db}`;')
        print(m.group(0))
        return 0

    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
