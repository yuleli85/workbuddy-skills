"""依赖清单读取 + 内置的常见高危组件版本表。

内置表只收了国内项目里最常见、出过大漏洞的组件，不能代替专业漏洞库；
装了 osv-scanner / npm audit / pip-audit 的，另外用它们查一遍更全。
"""
import json
import re
from pathlib import Path

# (生态, 包名, [(起始版本, 修复版本), ...] 或 'any', 级别, 说明)
# 版本落在 [起始, 修复) 任一区间就算受影响
KNOWN = [
    ('maven', 'com.alibaba:fastjson', [('0', '1.2.83')], '严重', '反序列化可远程执行代码（CVE-2022-25845 等），建议换 fastjson2'),
    ('maven', 'org.apache.logging.log4j:log4j-core', [('2.0', '2.17.1')], '严重', 'Log4Shell 远程执行代码（CVE-2021-44228 等）'),
    ('maven', 'log4j:log4j', 'any', '高', 'Log4j 1.x 已停止维护，有反序列化漏洞（CVE-2019-17571），换 Log4j2 或 Logback'),
    ('maven', 'org.springframework:spring-beans', [('0', '5.2.20'), ('5.3.0', '5.3.18')], '高', 'Spring4Shell（CVE-2022-22965）：JDK9 以上、打 war 包部署到 Tomcat 时可远程执行代码'),
    ('maven', 'org.springframework:spring-webmvc', [('0', '5.2.20'), ('5.3.0', '5.3.18')], '高', 'Spring4Shell（CVE-2022-22965）：JDK9 以上、打 war 包部署到 Tomcat 时可远程执行代码'),
    ('maven', 'org.springframework.boot:spring-boot-starter-parent', [('2.0', '2.5.12'), ('2.6.0', '2.6.6')], '高', '带的 Spring 版本受 Spring4Shell（CVE-2022-22965）影响'),
    ('maven', 'org.springframework.boot:spring-boot-dependencies', [('2.0', '2.5.12'), ('2.6.0', '2.6.6')], '高', '带的 Spring 版本受 Spring4Shell（CVE-2022-22965）影响'),
    ('maven', 'org.apache.shiro:shiro-core', [('0', '1.13.0')], '高', '多个认证绕过漏洞（CVE-2023-46749 等）；1.2.4 及以下还有 rememberMe 远程执行'),
    ('maven', 'org.apache.shiro:shiro-spring', [('0', '1.13.0')], '高', '多个认证绕过漏洞（CVE-2023-46749 等）'),
    ('maven', 'org.apache.shiro:shiro-web', [('0', '1.13.0')], '高', '多个认证绕过漏洞（CVE-2023-46749 等）'),
    ('maven', 'org.yaml:snakeyaml', [('0', '2.0')], '中', '解析不可信 YAML 可远程执行代码（CVE-2022-1471）'),
    ('maven', 'com.fasterxml.jackson.core:jackson-databind', [('0', '2.12.7.1'), ('2.13.0', '2.13.4.2')], '中', '多个反序列化、拒绝服务漏洞（CVE-2022-42003 等）'),
    ('maven', 'commons-collections:commons-collections', [('0', '3.2.2')], '高', '反序列化利用链（CVE-2015-7501）'),
    ('maven', 'org.apache.commons:commons-collections4', [('0', '4.1')], '高', '反序列化利用链（CVE-2015-7501）'),
    ('maven', 'commons-fileupload:commons-fileupload', [('0', '1.5')], '中', '上传请求可造成拒绝服务（CVE-2023-24998）'),
    ('maven', 'com.thoughtworks.xstream:xstream', [('0', '1.4.20')], '高', '反序列化远程执行等多个漏洞'),
    ('maven', 'org.apache.struts:struts2-core', [('0', '2.5.33'), ('6.0.0', '6.3.0.2')], '严重', '文件上传可远程执行代码（CVE-2023-50164）'),
    ('maven', 'com.h2database:h2', [('0', '2.1.210')], '高', '控制台可被远程执行代码（CVE-2021-42392）'),
    ('maven', 'mysql:mysql-connector-java', [('0', '8.0.28')], '中', '驱动漏洞（CVE-2021-2471），建议升级并换成 com.mysql:mysql-connector-j'),
    ('maven', 'org.apache.poi:poi', [('0', '4.1.1')], '中', '解析文件存在外部实体注入（CVE-2019-12415）'),
    ('maven', 'dom4j:dom4j', 'any', '中', '老版 dom4j 默认允许外部实体注入（CVE-2020-10683），换 org.dom4j:dom4j 2.1.3 以上'),
    ('maven', 'org.dom4j:dom4j', [('0', '2.1.3')], '中', '默认允许外部实体注入（CVE-2020-10683）'),
    ('npm', 'lodash', [('0', '4.17.21')], '高', '原型污染、命令注入（CVE-2021-23337）'),
    ('npm', 'axios', [('0', '0.28.0'), ('1.0.0', '1.6.0')], '中', '跨站请求伪造令牌泄露（CVE-2023-45857）'),
    ('npm', 'minimist', [('0', '1.2.6')], '中', '原型污染（CVE-2021-44906）'),
    ('npm', 'jsonwebtoken', [('0', '9.0.0')], '高', '令牌校验可被绕过（CVE-2022-23529 等）'),
    ('npm', 'express', [('0', '4.19.2')], '中', '开放跳转（CVE-2024-29041）'),
    ('npm', 'ejs', [('0', '3.1.7')], '严重', '模板注入远程执行代码（CVE-2022-29078）'),
    ('npm', 'handlebars', [('0', '4.7.7')], '严重', '原型污染导致远程执行代码（CVE-2021-23369）'),
    ('npm', 'moment', [('0', '2.29.4')], '中', '解析日期可被拒绝服务（CVE-2022-31129）'),
    ('npm', 'jquery', [('0', '3.5.0')], '中', '跨站脚本（CVE-2020-11022）'),
    ('npm', 'xlsx', [('0', '0.19.3')], '高', '原型污染（CVE-2023-30533）；npm 上的 xlsx 停在 0.18.5，要从 SheetJS 官方源装新版'),
    ('npm', 'node-serialize', 'any', '严重', '反序列化远程执行代码（CVE-2017-5941），不要用'),
    ('npm', 'crypto-js', [('0', '4.2.0')], '中', 'PBKDF2 默认参数太弱（CVE-2023-46233）'),
    ('npm', 'vue', [('2.0.0', '3.0.0')], '低', 'Vue 2 已于 2023 年底停止维护，不再有安全更新'),
    ('pypi', 'pyyaml', [('0', '5.4')], '严重', 'yaml.load 可远程执行代码（CVE-2020-14343）'),
    ('pypi', 'requests', [('0', '2.31.0')], '中', '跳转时泄露代理凭据（CVE-2023-32681）'),
    ('pypi', 'jinja2', [('0', '3.1.3')], '中', '跨站脚本（CVE-2024-22195）'),
    ('pypi', 'pillow', [('0', '10.0.1')], '高', '处理 WebP 图片时堆溢出（CVE-2023-4863）'),
    ('pypi', 'flask', [('0', '2.2.5'), ('2.3.0', '2.3.2')], '中', '缓存代理下可能串会话（CVE-2023-30861）'),
    ('pypi', 'urllib3', [('0', '1.26.18'), ('2.0.0', '2.0.7')], '中', '跳转时泄露请求头（CVE-2023-43804 等）'),
    ('pypi', 'werkzeug', [('0', '2.2.3')], '中', '多段上传拒绝服务（CVE-2023-25577）'),
    ('pypi', 'pycrypto', 'any', '高', '已停止维护，有缓冲区溢出（CVE-2013-7459），改用 pycryptodome'),
    ('go', 'github.com/dgrijalva/jwt-go', 'any', '高', '已停止维护，令牌校验可被绕过（CVE-2020-26160），改用 github.com/golang-jwt/jwt'),
]


def vtuple(v):
    nums = re.findall(r'\d+', v or '')
    return tuple(int(n) for n in nums[:4]) + (0,) * (4 - min(len(nums), 4))


def affected(version, ranges):
    if ranges == 'any':
        return True
    if not version or not re.search(r'\d', version):
        return None
    v = vtuple(version)
    return any(vtuple(lo) <= v < vtuple(hi) for lo, hi in ranges)


def _clean_spec(spec):
    spec = (spec or '').strip()
    m = re.search(r'\d+(\.\d+)*([.\-][\w]+)?', spec)
    return m.group(0) if m else ''


def _read(p):
    try:
        return Path(p).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def parse_pom(path):
    text = _read(path)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    props = dict(re.findall(r'<([\w.\-]+)>\s*([^<\s][^<]*?)\s*</\1>', re.search(r'<properties>(.*?)</properties>', text, re.S).group(1))) if '<properties>' in text else {}
    proj_ver = re.search(r'</parent>.*?<version>([^<]+)</version>', text, re.S)
    if proj_ver:
        props.setdefault('project.version', proj_ver.group(1).strip())

    def resolve(v):
        for _ in range(3):
            m = re.fullmatch(r'\$\{([^}]+)\}', v or '')
            if not m:
                break
            v = props.get(m.group(1), v)
        return v
    out = []
    for tag in ('parent', 'dependency', 'plugin'):
        for blk in re.findall(r'<%s>(.*?)</%s>' % (tag, tag), text, re.S):
            g = re.search(r'<groupId>([^<]+)</groupId>', blk)
            a = re.search(r'<artifactId>([^<]+)</artifactId>', blk)
            v = re.search(r'<version>([^<]+)</version>', blk)
            if not a:
                continue
            ver = resolve(v.group(1).strip()) if v else ''
            out.append({'eco': 'maven', 'name': '%s:%s' % (g.group(1).strip() if g else '', a.group(1).strip()),
                        'version': '' if ver.startswith('${') else ver, 'spec': ver, 'kind': tag})
    return out


def parse_gradle(path):
    out = []
    for g, a, v in re.findall(r'["\']([\w.\-]+):([\w.\-]+):([\w.\-${}]+)["\']', _read(path)):
        out.append({'eco': 'maven', 'name': '%s:%s' % (g, a), 'version': _clean_spec(v), 'spec': v})
    return out


def _lock_versions(pkg_dir):
    lock = pkg_dir / 'package-lock.json'
    vers = {}
    if lock.exists():
        try:
            data = json.loads(_read(lock))
            for k, v in (data.get('packages') or {}).items():
                if k.startswith('node_modules/') and k.count('node_modules/') == 1:
                    vers[k[len('node_modules/'):]] = v.get('version', '')
            for k, v in (data.get('dependencies') or {}).items():
                vers.setdefault(k, v.get('version', ''))
        except (ValueError, AttributeError):
            pass
    ylock = pkg_dir / 'yarn.lock'
    if ylock.exists():
        cur = None
        for line in _read(ylock).splitlines():
            if line and not line.startswith(' ') and not line.startswith('#'):
                first = line.split(',')[0].strip().strip('"').rstrip(':')
                cur = first.rsplit('@', 1)[0] if first.count('@') >= 1 else None
            else:
                m = re.match(r'\s+version:?\s+"?([^"\s]+)"?', line)
                if m and cur:
                    vers.setdefault(cur, m.group(1))
                    cur = None
    return vers


def parse_package_json(path):
    try:
        data = json.loads(_read(path))
    except ValueError:
        return [], {}
    locks = _lock_versions(Path(path).parent)
    out = []
    for kind in ('dependencies', 'devDependencies'):
        for name, spec in (data.get(kind) or {}).items():
            spec = str(spec)
            ver = locks.get(name) or _clean_spec(spec)
            out.append({'eco': 'npm', 'name': name, 'version': ver, 'spec': spec,
                        'kind': 'dev' if kind == 'devDependencies' else '', 'locked': name in locks})
    return out, data.get('scripts') or {}


def parse_requirements(path):
    out = []
    for line in _read(path).splitlines():
        line = line.split('#')[0].strip()
        m = re.match(r'([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(==|>=|~=|<=|>|<)?\s*([\w.]*)', line)
        if m and not line.startswith('-'):
            out.append({'eco': 'pypi', 'name': m.group(1).lower().replace('_', '-'), 'version': m.group(4) if m.group(3) in ('==', '>=', '~=') else '', 'spec': line})
    return out


def parse_pyproject(path):
    out = []
    for name, op, ver in re.findall(r'["\']([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(==|>=|~=|\^)\s*([\d.]+)', _read(path)):
        out.append({'eco': 'pypi', 'name': name.lower().replace('_', '-'), 'version': ver, 'spec': op + ver})
    return out


def parse_gomod(path):
    out = []
    for name, ver in re.findall(r'^\s*(?:require\s+)?([\w.\-]+\.[\w.\-/]+)\s+v([\w.\-+]+)', _read(path), re.M):
        out.append({'eco': 'go', 'name': name, 'version': ver, 'spec': 'v' + ver})
    return out


def collect(files, root):
    """files：项目里所有相对路径。返回 (依赖列表, 有问题的依赖, npm scripts)。"""
    deps, scripts = [], {}
    for rel in files:
        name = rel.rsplit('/', 1)[-1]
        p = Path(root) / rel
        got = []
        if name == 'pom.xml':
            got = parse_pom(p)
        elif name in ('build.gradle', 'build.gradle.kts'):
            got = parse_gradle(p)
        elif name == 'package.json':
            got, sc = parse_package_json(p)
            if rel.count('/') == 0 or not scripts:
                scripts.update({k: v for k, v in sc.items()})
        elif re.fullmatch(r'requirements[\w\-.]*\.txt', name):
            got = parse_requirements(p)
        elif name == 'pyproject.toml':
            got = parse_pyproject(p)
        elif name == 'go.mod':
            got = parse_gomod(p)
        for d in got:
            d['file'] = rel
        deps.extend(got)
    risky = []
    for d in deps:
        for eco, name, ranges, level, desc in KNOWN:
            if d['eco'] == eco and d['name'].lower() == name.lower():
                hit = affected(d['version'], ranges)
                if hit:
                    fixed = '' if ranges == 'any' else next((hi for lo, hi in ranges if vtuple(lo) <= vtuple(d['version']) < vtuple(hi)), '')
                    risky.append(dict(d, level=level, desc=desc, fixed=fixed,
                                      approx=(d['eco'] == 'npm' and not d.get('locked'))))
                elif hit is None and ranges != 'any':
                    risky.append(dict(d, level='待核', desc='版本由上级工程或依赖管理指定，没读到具体版本；' + desc, fixed=ranges[-1][1], approx=True))
    return deps, risky, scripts
