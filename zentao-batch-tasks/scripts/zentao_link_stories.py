#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道：把需求(story)关联到执行(execution)。

背景（源码级事实，执行 model.php::linkStory）：
    $notAllowedStatus = $this->app->rawMethod == 'batchcreate' ? 'closed' : 'draft,reviewing,closed';
    ...
    if(strpos($notAllowedStatus, (string)$storyList[$storyID]->status) !== false) continue;
即 **状态为 draft / reviewing / closed 的需求会被静默跳过**，接口照样返回「保存成功」。
所以「评审中」的需求必须先评审通过（status -> active）才能关联。

用法：
    # 仅关联（需求已是 active）
    python3 zentao_link_stories.py --account admin --password 'xxx' --execution 29 --stories 314,315

    # 先评审通过再关联
    python3 zentao_link_stories.py --account admin --password 'xxx' --execution 29 \
        --stories 314,315,316,318,320 --review-pass

    # 只看状态，不动数据
    python3 zentao_link_stories.py --account admin --password 'xxx' --execution 29 --stories 314 --check-only
"""
import argparse
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class Zen:
    def __init__(self, base, account, password):
        self.base = base.rstrip('/')
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self._login(account, password)

    def _req(self, path, data=None, ajax=True, referer=None):
        req = urllib.request.Request(self.base + path, data=data, method='POST' if data else 'GET')
        req.add_header('User-Agent', UA)
        req.add_header('Referer', referer or (self.base + '/'))
        if ajax:
            req.add_header('X-Requested-With', 'XMLHttpRequest')   # 缺了它禅道不回 JSON
        if data:
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        return self.op.open(req, timeout=30).read().decode('utf-8', 'replace')

    def _login(self, account, password):
        login_url = '/index.php?m=user&f=login'
        self._req(login_url, ajax=False)
        rand = self._req('/index.php?m=user&f=refreshRandom', referer=self.base + login_url).strip()
        enc = hashlib.md5((hashlib.md5(password.encode()).hexdigest() + rand).encode()).hexdigest()
        body = urllib.parse.urlencode({
            'account': account, 'password': enc, 'passwordStrength': 3,
            'referer': '/', 'verifyRand': rand, 'keepLogin': 0, 'captcha': '',
        }).encode()
        # Referer 必带，否则被 Cloudflare 挡成 HTML 登录页
        resp = self._req(login_url, data=body, referer=self.base + login_url)
        if '"result":"success"' not in resp.replace(' ', ''):
            raise SystemExit(f'登录失败: {resp[:200]}')

    def token(self):
        req = urllib.request.Request(self.base + '/api.php/v1/tokens',
                                     data=json.dumps({'account': None, 'password': None}).encode())
        raise NotImplementedError

    def api(self, path, token):
        req = urllib.request.Request(self.base + path)
        req.add_header('Token', token)
        req.add_header('User-Agent', UA)
        req.add_header('Accept', 'application/json')
        return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

    def story(self, sid, token):
        return self.api(f'/api.php/v1/stories/{sid}', token)

    def linked(self, execution, token):
        d = self.api(f'/api.php/v1/executions/{execution}/stories', token)
        return sorted(s['id'] for s in d.get('stories', d))

    def review_pass(self, sid, comment=''):
        """评审通过：status reviewing -> active

        注意 status 必须显式提交：storyModel::review() 会把表单字段整体覆盖写库
        （$skipFields 只排除 finalResult/result/comment），漏传 status 会被写成空字符串。
        """
        body = urllib.parse.urlencode({
            'reviewedDate': time.strftime('%Y-%m-%d %H:%M:%S'),
            'result': 'pass',
            'status': 'active',
            'comment': comment,
        }).encode()
        url = f'/index.php?m=story&f=review&storyID={sid}'
        return self._req(url, data=body, referer=self.base + url)[:200]

    def link(self, execution, stories):
        body = urllib.parse.urlencode([('stories[]', str(s)) for s in stories]).encode()
        url = f'/index.php?m=execution&f=linkStory&executionID={execution}'
        return self._req(url, data=body, referer=self.base + url)[:200]


def rest_token(base, account, password):
    req = urllib.request.Request(base.rstrip('/') + '/api.php/v1/tokens',
                                 data=json.dumps({'account': account, 'password': password}).encode(),
                                 method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', UA)
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())['token']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='https://zen.mzlc.me')
    ap.add_argument('--account', required=True)
    ap.add_argument('--password', required=True)
    ap.add_argument('--execution', type=int, required=True)
    ap.add_argument('--stories', required=True, help='需求ID，逗号分隔')
    ap.add_argument('--review-pass', action='store_true', help='关联前先执行「评审通过」')
    ap.add_argument('--comment', default='')
    ap.add_argument('--check-only', action='store_true', help='只打印状态，不改数据')
    args = ap.parse_args()

    sids = [int(x) for x in args.stories.replace(' ', '').split(',') if x]
    token = rest_token(args.base, args.account, args.password)
    z = Zen(args.base, args.account, args.password)

    print('执行 %d 当前已关联需求: %s' % (args.execution, z.linked(args.execution, token)))
    for sid in sids:
        s = z.story(sid, token)
        print(f'  需求 #{sid}  状态={s.get("status"):<10} 阶段={s.get("stage"):<10} {s.get("title","")[:20]}')
    if args.check_only:
        return

    if args.review_pass:
        for sid in sids:
            s = z.story(sid, token)
            if s.get('status') == 'active':
                print(f'  [跳过评审] #{sid} 已 active')
                continue
            r = z.review_pass(sid, args.comment)
            print(f'  [评审通过] #{sid} -> {r}')
            time.sleep(0.3)
        time.sleep(1)
        for sid in sids:
            print(f'  [复核] #{sid} status = {z.story(sid, token).get("status")}')

    print('[关联] POST f=linkStory ...')
    print('  resp:', z.link(args.execution, sids))
    time.sleep(1)
    after = z.linked(args.execution, token)
    print('关联后:', after)
    missing = [s for s in sids if s not in after]
    if missing:
        print('⚠️ 仍未关联:', missing)
        sys.exit(1)
    print('✅ 全部关联成功')


if __name__ == '__main__':
    main()
