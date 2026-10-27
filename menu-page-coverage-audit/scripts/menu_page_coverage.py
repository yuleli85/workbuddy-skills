#!/usr/bin/env python3
"""菜单-页面覆盖审计：找出「菜单点开没有网页」的条目。

用法：
    # 1) 先导出菜单表为 TSV（列序固定，见下）
    #    menu_id name path component parent_id menu_type visible del_flag
    # 2) 再比对前端工程
    python menu_page_coverage.py --menu-tsv sys_menu.tsv \
        --front web=./front-web/src/views \
        --front pc=./front-pc/src/views

TSV 里的 NULL 会被当空值处理；`component` 为空时按前端回落逻辑用 `path` 推导。
"""
import argparse
import os
import sys

NULLS = ('', 'NULL', 'null', 'None')


def load_menu(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            p = line.rstrip('\n').split('\t')
            if len(p) < 8:
                continue
            rows.append(dict(id=p[0], name=p[1], path=p[2], comp=p[3],
                             pid=p[4], mtype=p[5], vis=p[6], delf=p[7]))
    return rows


def collect_components(views_dir):
    """扫描 views 目录，返回「相对 views 的路径（去掉 .vue/.tsx）」集合。"""
    out = set()
    for dirpath, _, filenames in os.walk(views_dir):
        if 'node_modules' in dirpath:
            continue
        for fn in filenames:
            if fn.endswith(('.vue', '.tsx')):
                rel = os.path.relpath(os.path.join(dirpath, fn), views_dir)[:-4]
                out.add(rel.replace(os.sep, '/'))
    return out


def resolve_component(row, exclude_prefixes=()):
    """模拟前端路由的组件解析：componentPath 优先，否则用 path 去前导 '/' 推导。

    返回 None 表示「无需组件」（外链菜单）。返回的路径若命中 exclude_prefixes
    则视为不可装配（对应 import.meta.glob 的负模式）。
    """
    c = row['comp']
    if c not in NULLS:
        key = c
    else:
        pth = row['path']
        if pth in NULLS or pth.startswith('http'):
            return None          # 外链：走 link.vue / iframes.vue，component 为空属正常
        key = pth.lstrip('/')
    for pref in exclude_prefixes:
        if key.startswith(pref):
            return '__EXCLUDED__' + key
    return key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--menu-tsv', required=True, help='sys_menu 导出的 TSV')
    ap.add_argument('--front', action='append', required=True,
                    metavar='NAME=VIEWS_DIR',
                    help='前端工程：名称=src/views 目录，可重复')
    ap.add_argument('--exclude-prefix', action='append', default=[],
                    help='被 glob 负模式排除的路径前缀，如 linmo/ （可重复）')
    args = ap.parse_args()

    rows = load_menu(args.menu_tsv)
    fronts = {}
    for spec in args.front:
        if '=' not in spec:
            sys.exit(f'--front 需写成 NAME=DIR，收到：{spec}')
        name, d = spec.split('=', 1)
        if not os.path.isdir(d):
            sys.exit(f'目录不存在：{d}')
        fronts[name] = collect_components(d)

    # 目录判定：有未删除子节点即为目录
    children = {}
    for r in rows:
        if r['delf'] == '0':
            children.setdefault(r['pid'], []).append(r)

    cands = [r for r in rows if r['mtype'] == '0' and r['vis'] == '1' and r['delf'] == '0']
    dirs = sum(1 for r in cands if children.get(r['id']))

    print(f'可见菜单页 {len(cands)} 条（目录节点 {dirs} 条已豁免）\n')

    total_bad = 0
    for name, comps in fronts.items():
        bad, external = [], []
        for r in cands:
            if children.get(r['id']):
                continue
            key = resolve_component(r, args.exclude_prefix)
            if key is None:
                external.append(r)
                continue
            if key.startswith('__EXCLUDED__'):
                bad.append((r, key[len('__EXCLUDED__'):], '被 glob 负模式排除'))
                continue
            if key not in comps:
                bad.append((r, key, 'views 下无此文件'))
        total_bad += len(bad)
        print(f'===== [{name}] 打不开：{len(bad)} 条 =====')
        if not bad:
            print('  （无 —— 全部可加载）')
        for r, k, why in bad:
            print(f"  {r['id']:>6}  {r['name']:<18} path={str(r['path']):<30} → {k}  [{why}] 父={r['pid']}")
        print(f'  （另有外链菜单 {len(external)} 条，component 为空属正常）\n')

    print('提示：静态比对只能定位「候选」。请再用浏览器实渲染每端各探一次 ——')
    print('      单端报错 ⇒ 该端缺组件副本（移植遗漏）；两端都报错 ⇒ 菜单配置错。')


if __name__ == '__main__':
    main()
