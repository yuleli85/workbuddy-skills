import sys, json, hashlib, urllib.request, urllib.parse, http.cookiejar, re

BASE = "https://zen.mzlc.me"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def req(url, data=None, headers=None, method=None):
    h = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"}
    if headers: h.update(headers)
    body = None
    if data is not None:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = data if isinstance(data, bytes) else data.encode()
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    with op.open(r, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")

def login(account, password):
    st, body = req(BASE + "/index.php?m=user&f=refreshRandom")
    rand = body.strip().strip('"')
    if not re.fullmatch(r"\d+", rand):
        return False, "refreshRandom 异常: " + body[:200]
    pwd = hashlib.md5((hashlib.md5(password.encode()).hexdigest() + rand).encode()).hexdigest()
    st, body = req(BASE + "/index.php?m=user&f=login", {
        "account": account, "password": pwd, "passwordStrength": 1,
        "referer": "/", "verifyRand": rand, "keepLogin": 0, "captcha": "",
    }, {"Referer": BASE + "/"})
    try:
        j = json.loads(body)
        return j.get("result") == "success", body[:300]
    except Exception:
        return False, body[:300]

if __name__ == "__main__":
    ok, msg = login("admin", "Linmo@2026Strong")
    print("login:", ok, msg)
    if ok:
        # 列出 cookie 里的 zentaosid
        for c in cj:
            if c.name == "zentaosid":
                print("zentaosid:", c.value)
