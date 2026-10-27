"""扫描项目：概况、交付物、自动规则、配置一致性、依赖、重复代码、测试。"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from . import deps as depmod
from .rules import RULES, COMMENT_LINE, VENDOR_PATH, SECRET_FILE, SECRET_FILE_OK, mask, CODE, D_SEC, D_DELIV, D_STYLE, D_REASON, D_TEST, D_BUG, D_DEP

SKIP_DIRS = {'.git', 'node_modules', 'dist', 'build', 'target', 'out', 'vendor', '.venv', 'venv', 'env',
             '__pycache__', '.idea', '.vscode', 'coverage', '.next', '.nuxt', 'unpackage', 'miniprogram_npm',
             '.gradle', '.mvn', 'bower_components', '.pytest_cache', '.tox', 'site-packages', '.svn', '.hg',
             'uni_modules', '.history', '.cache', 'logs', '.output', 'bin', 'obj', '.dart_tool', 'Pods'}
JUNK_DIRS = {'node_modules', 'target', 'dist', '__pycache__', '.idea', '.vscode', 'unpackage', '.gradle', 'logs', 'obj'}
SKIP_FILE = re.compile(r'(\.min\.(js|css)$|\.map$|-lock\.json$|\.lock$|pnpm-lock\.yaml$|\.bundle\.js$|\.chunk\.js$)')

LANG = {'.java': 'Java', '.kt': 'Kotlin', '.scala': 'Scala', '.groovy': 'Groovy', '.js': 'JavaScript', '.mjs': 'JavaScript',
        '.cjs': 'JavaScript', '.jsx': 'JavaScript', '.ts': 'TypeScript', '.tsx': 'TypeScript', '.vue': 'Vue',
        '.nvue': 'Vue', '.svelte': 'Svelte', '.py': 'Python', '.go': 'Go', '.php': 'PHP', '.cs': 'C#', '.rb': 'Ruby',
        '.c': 'C', '.cpp': 'C++', '.h': 'C/C++', '.rs': 'Rust', '.swift': 'Swift', '.dart': 'Dart', '.m': 'Objective-C',
        '.sql': 'SQL', '.sh': 'Shell', '.bash': 'Shell', '.ps1': 'PowerShell', '.bat': '批处理', '.cmd': '批处理',
        '.html': 'HTML', '.htm': 'HTML', '.jsp': 'JSP', '.wxml': '小程序页面', '.css': '样式', '.scss': '样式',
        '.less': '样式', '.wxss': '样式'}
DOC_EXT = {'.md', '.txt', '.docx', '.doc', '.pdf', '.wps', '.html', '.htm', '.rst', '.adoc', '.xlsx', '.xls', '.pptx'}

TEST_PATH = re.compile(r'(^|/)(test|tests|__tests__|spec|specs|e2e|testing)(/|$)|(Test|Tests|IT)\.(java|kt|cs)$|_test\.(go|py)$|(^|/)test_[^/]+\.py$|\.(spec|test)\.[cm]?[jt]sx?$|(^|/)src/test/', re.I)


def read_text(path, limit=2_000_000):
    try:
        if path.stat().st_size > limit:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b'\0' in data[:8000]:
        return None
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode('latin-1')


def ext_of(rel):
    name = rel.rsplit('/', 1)[-1]
    if name.lower().startswith('dockerfile') or name.lower().endswith('.dockerfile'):
        return 'dockerfile'
    if name.startswith('.env'):
        return '.env'
    return os.path.splitext(name)[1].lower()


def git(root, *args):
    try:
        r = subprocess.run(['git', '-C', str(root)] + list(args), capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def walk(root, excludes):
    files, junk = [], set()
    for dp, dns, fns in os.walk(root):
        rel_dir = os.path.relpath(dp, root).replace('\\', '/')
        rel_dir = '' if rel_dir == '.' else rel_dir + '/'
        keep = []
        for d in dns:
            r = rel_dir + d
            if any(r == e or r.startswith(e + '/') for e in excludes):
                continue
            if d in SKIP_DIRS:
                if d in JUNK_DIRS:
                    junk.add(r)
                continue
            keep.append(d)
        dns[:] = sorted(keep)
        for f in sorted(fns):
            r = rel_dir + f
            if not any(r == e or r.startswith(e + '/') for e in excludes):
                files.append(r)
    return files, sorted(junk)


def docx_text(path):
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'replace')
            images = len([n for n in z.namelist() if n.startswith('word/media/')])
    except Exception:
        return '', 0
    xml = re.sub(r'</w:p>', '\n', xml)
    return re.sub(r'<[^>]+>', '', xml), images


def pdf_text(path):
    exe = shutil.which('pdftotext')
    if not exe:
        return None
    try:
        r = subprocess.run([exe, '-layout', str(path), '-'], capture_output=True, text=True, timeout=60)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------- 交付物 ----------------
DELIV = [
    # 名称, 文件名正则, 内容要点 [(要点, 正则)]
    ('需求或设计文档', r'(需求|设计|PRD|规格|spec|概要|详细设计|原型|功能清单|功能说明)', []),
    ('用户使用手册', r'(用户手册|使用手册|操作手册|使用说明|用户指南|操作指南|操作说明|user[-_ ]?(guide|manual)|使用指南)', [
        ('登录和账号', r'登录|账号|帐号|login'),
        ('各功能模块的操作步骤', r'功能|模块|菜单|操作步骤|点击'),
        ('角色和权限说明', r'角色|权限|管理员'),
        ('配图或截图', None),
        ('常见问题', r'常见问题|FAQ|疑问|注意事项')]),
    ('部署手册', r'(部署|安装手册|安装说明|安装指南|运维手册|实施手册|上线手册|deploy|install|setup|运维)', [
        ('环境要求（系统、软件和版本）', r'环境|版本|JDK|Java\s*\d|Node|Python|MySQL|Redis|Nginx|操作系统|CentOS|Ubuntu|内存|CPU'),
        ('配置项说明', r'配置|环境变量|\.ya?ml|\.env|\.properties|config'),
        ('数据库初始化', r'数据库|建库|初始化|\.sql|migrat|导入'),
        ('构建和启动步骤', r'启动|运行|构建|打包|start|run|build|docker'),
        ('部署后怎么验证', r'验证|检查|访问|健康|health|确认'),
        ('升级和回滚', r'升级|回滚|rollback|upgrade|还原'),
        ('备份', r'备份|backup'),
        ('常见问题和排错', r'常见问题|FAQ|排错|故障|报错|问题处理')]),
    ('接口文档', r'(接口文档|接口说明|api[-_ ]?(doc|文档|说明)|openapi|swagger|postman|apifox)', []),
    ('测试报告', r'(测试报告|test[-_ ]?report|测试用例|验收报告)', []),
    ('版本说明', r'(changelog|版本说明|更新日志|release|版本记录|变更记录)', []),
]


def classify_docs(files, root):
    docs = defaultdict(list)
    texts = {}
    for rel in files:
        e = ext_of(rel)
        name = rel.rsplit('/', 1)[-1]
        if e not in DOC_EXT and not re.search(r'(openapi|swagger)[\w.\-]*\.(json|ya?ml)$', name, re.I) and not name.endswith('.postman_collection.json'):
            continue
        if e in {'.html', '.htm'} and not re.search(r'(^|/)(docs?|文档|手册)/', rel, re.I):
            continue
        for title, pat, _ in DELIV:
            if re.search(pat, name, re.I) or (title == '接口文档' and re.search(pat, rel, re.I) and e in {'.json', '.yaml', '.yml', '.md'}):
                docs[title].append(rel)
        if re.match(r'readme', name, re.I):
            docs['README'].append(rel)
        if re.match(r'(license|licence|notice|copying)', name, re.I) or '许可' in name:
            docs['许可证'].append(rel)
    return docs


def doc_content(root, rel):
    p = Path(root) / rel
    e = ext_of(rel)
    if e == '.docx':
        return docx_text(p)
    if e == '.pdf':
        t = pdf_text(p)
        return (t, 0) if t is not None else (None, 0)
    if e in {'.doc', '.wps', '.xlsx', '.xls', '.pptx'}:
        return None, 0
    t = read_text(p) or ''
    return t, len(re.findall(r'!\[|<img\b', t))


def assess_deliverables(files, root, docs, stack, tests, scripts, junk_tracked):
    out = []
    all_doc_text = []

    def contents(rels):
        parts, imgs, unread = [], 0, []
        for r in rels:
            t, n = doc_content(root, r)
            if t is None:
                unread.append(r)
            else:
                parts.append(t)
                imgs += n
        return '\n'.join(parts), imgs, unread

    readme_text = contents(docs.get('README', []))[0]
    for title, pat, points in DELIV:
        rels = docs.get(title, [])
        text, imgs, unread = contents(rels)
        all_doc_text.append(text)
        item = {'item': title, 'files': rels, 'auto': '', 'missing': [], 'note': ''}
        if title == '接口文档' and not rels and stack.get('apidoc'):
            item.update(auto='代码自带', note='代码里用了 %s，接口文档由程序启动后生成（要确认生产环境的开关和访问控制）' % stack['apidoc'])
            out.append(item)
            continue
        if not rels:
            # README 里写了也算一部分
            if title in ('部署手册', '用户使用手册') and readme_text:
                hit = [p for p, rx in points if rx and re.search(rx, readme_text, re.I)]
                if len(hit) >= 2:
                    item.update(auto='不全', files=docs.get('README', []), note='没有单独的%s，README 里写了一部分' % title,
                                missing=[p for p, rx in points if rx and p not in hit])
                    out.append(item)
                    continue
            item['auto'] = '缺失'
            out.append(item)
            continue
        if points:
            miss = []
            for p, rx in points:
                if rx is None:
                    if imgs == 0:
                        miss.append(p)
                elif not re.search(rx, text, re.I):
                    miss.append(p)
            item['missing'] = miss
            item['auto'] = '齐全' if not miss else '不全'
            if unread:
                item['note'] = '%s 是程序读不了的格式，要人工打开看' % '、'.join(unread)
                if not text:
                    item['auto'] = '待核'
        else:
            item['auto'] = '有'
        out.append(item)

    sqls = [f for f in files if ext_of(f) == '.sql']
    migr = [f for f in files if re.search(r'(^|/)(migrations?|db/migration|alembic|flyway|liquibase|changelog)/', f, re.I)]
    out.append({'item': '数据库脚本', 'files': (sqls + migr)[:30], 'auto': '有' if (sqls or migr or stack.get('orm_auto')) else ('不适用' if not stack.get('db') else '缺失'),
                'missing': [], 'note': ('用 %s 自动建表；仍要有初始化数据（管理员账号、字典）的脚本或说明' % stack['orm_auto']) if (stack.get('orm_auto') and not sqls) else ''})
    build = [f for f in files if re.search(r'(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml|Makefile|[^/]+\.(sh|bat|cmd|ps1)|pom\.xml|build\.gradle(\.kts)?|package\.json|requirements[^/]*\.txt|pyproject\.toml|go\.mod|Jenkinsfile|\.gitlab-ci\.yml|nginx[^/]*\.conf)$', f)]
    has_start = bool([f for f in build if re.search(r'(start|run|deploy|启动|部署|install)', f, re.I)] or 'start' in scripts or 'serve' in scripts or any('Dockerfile' in f or 'compose' in f for f in build))
    out.append({'item': '构建和启动脚本', 'files': build[:30], 'auto': ('有' if has_start else '不全') if build else '缺失',
                'missing': [] if has_start else ['一键启动或部署脚本（Dockerfile、启动停止脚本等）'], 'note': ''})
    conf = [f for f in files if re.search(r'(^|/)(\.env\.(example|sample|template)|[^/]*\.example(\.\w+)?|application[^/]*\.(ya?ml|properties)|config[^/]*\.(ya?ml|json|js|ts|toml|ini|py)|settings[^/]*\.py|\.env\.[a-z]+)$', f, re.I)]
    sample = [f for f in conf if re.search(r'example|sample|template', f, re.I)]
    out.append({'item': '配置样例', 'files': conf[:30], 'auto': ('有' if sample else '不全') if conf else '缺失',
                'missing': [] if sample else ['不带真实口令的配置样例（如 .env.example），写清每个配置项'], 'note': ''})
    tstatus = '缺失' if tests['testFiles'] == 0 else ('有' if tests['testFiles'] >= max(3, tests['srcFiles'] // 20) else '不全')
    out.append({'item': '自动化测试', 'files': tests['sample'], 'auto': tstatus, 'missing': [],
                'note': '测试文件 %d 个，源代码文件 %d 个' % (tests['testFiles'], tests['srcFiles'])})
    out.append({'item': 'README', 'files': docs.get('README', []), 'auto': '有' if docs.get('README') else '缺失', 'missing': [], 'note': ''})
    out.append({'item': '许可证和第三方声明', 'files': docs.get('许可证', []), 'auto': '有' if docs.get('许可证') else '缺失', 'missing': [],
                'note': '' if docs.get('许可证') else '交付给客户的项目一般要写明代码归属和用到的开源组件许可'})
    return out, '\n'.join(all_doc_text) + '\n' + readme_text


# ---------------- 技术栈 ----------------
def detect_stack(files, root, deps):
    names = {d['name'].lower() for d in deps}
    s = {'frameworks': [], 'db': False}
    checks = [('Spring Boot', lambda: any(n.startswith('org.springframework.boot:') for n in names)),
              ('MyBatis', lambda: any('mybatis' in n for n in names)),
              ('若依', lambda: any('ruoyi' in n for n in names) or any('ruoyi' in f.lower() for f in files[:500])),
              ('Vue', lambda: 'vue' in names), ('React', lambda: 'react' in names),
              ('uni-app', lambda: any(f.endswith('pages.json') for f in files) and any(f.endswith('manifest.json') for f in files)),
              ('微信小程序', lambda: any(f.endswith('app.json') for f in files) and any(f.endswith('.wxml') for f in files)),
              ('Express', lambda: 'express' in names), ('NestJS', lambda: '@nestjs/core' in names), ('Koa', lambda: 'koa' in names),
              ('Django', lambda: 'django' in names), ('Flask', lambda: 'flask' in names), ('FastAPI', lambda: 'fastapi' in names),
              ('Gin', lambda: 'github.com/gin-gonic/gin' in names), ('Laravel', lambda: any(f.endswith('artisan') for f in files)),
              ('ThinkPHP', lambda: any('thinkphp' in f.lower() for f in files[:2000]))]
    for name, fn in checks:
        try:
            if fn():
                s['frameworks'].append(name)
        except Exception:
            pass
    db_words = ('mysql', 'postgres', 'sqlite', 'mongo', 'redis', 'oracle', 'sqlserver', 'mssql', 'dm', 'sequelize', 'typeorm', 'prisma', 'mybatis', 'hibernate', 'jpa', 'sqlalchemy', 'pymysql', 'gorm', 'mongoose', 'django')
    s['db'] = any(any(w in n for w in db_words) for n in names) or any(ext_of(f) == '.sql' for f in files)
    for key, label in (('springdoc', 'springdoc'), ('knife4j', 'Knife4j'), ('swagger', 'Swagger'), ('fastapi', 'FastAPI 自带文档'), ('drf-spectacular', 'drf-spectacular'), ('@nestjs/swagger', 'Nest Swagger')):
        if any(key in n for n in names):
            s['apidoc'] = label
            break
    for key, label in (('spring-boot-starter-data-jpa', 'JPA'), ('flyway', 'Flyway'), ('liquibase', 'Liquibase'), ('django', 'Django 迁移'), ('alembic', 'Alembic'), ('prisma', 'Prisma'), ('typeorm', 'TypeORM'), ('sequelize', 'Sequelize')):
        if any(key in n for n in names):
            s['orm_auto'] = label
            break
    cmds = []
    if any(f.endswith('pom.xml') for f in files):
        cmds += ['mvn -q -DskipTests package', 'mvn test']
    if any(re.search(r'build\.gradle', f) for f in files):
        cmds += ['./gradlew build']
    if any(f.endswith('package.json') for f in files):
        cmds += ['npm ci（或 pnpm i / yarn）', 'npm run build', 'npm test']
    if any(f.endswith(('requirements.txt', 'pyproject.toml')) for f in files):
        cmds += ['pip install -r requirements.txt', 'python -m pytest', 'python -m compileall -q .']
    if any(f.endswith('go.mod') for f in files):
        cmds += ['go build ./...', 'go vet ./...', 'go test ./...']
    if any(f.endswith('docker-compose.yml') or f.endswith('compose.yml') for f in files):
        cmds += ['docker compose config', 'docker compose up -d']
    s['commands'] = cmds
    return s


# ---------------- 配置一致性 ----------------
ENV_RE = [r'process\.env\.([A-Z_][A-Z0-9_]*)', r'process\.env\[\s*[\'"]([A-Z_][A-Z0-9_]*)', r'import\.meta\.env\.([A-Z_][A-Z0-9_]*)',
          r'os\.environ(?:\.get)?\s*[\(\[]\s*[\'"]([A-Z_][A-Z0-9_]*)', r'os\.getenv\(\s*[\'"]([A-Z_][A-Z0-9_]*)', r'System\.getenv\(\s*"([A-Z_][A-Z0-9_]*)"',
          r'os\.Getenv\(\s*"([A-Z_][A-Z0-9_]*)"', r'(?<![\w>])getenv\(\s*[\'"]([A-Z_][A-Z0-9_]*)', r'(?<![\w.])env\(\s*[\'"]([A-Z_][A-Z0-9_]*)',
          r'Environment\.GetEnvironmentVariable\(\s*"([A-Z_][A-Z0-9_]*)"']
ENV_IN_CONF = r'\$\{([A-Z_][A-Z0-9_]*)(:[^}]*)?\}'
ENV_COMMON = {'NODE_ENV', 'PATH', 'HOME', 'USER', 'PWD', 'TZ', 'CI', 'LANG', 'TMPDIR', 'TEMP', 'SHELL', 'BASE_URL', 'DEV', 'PROD', 'MODE', 'SSR', 'JAVA_HOME', 'HOSTNAME', 'TERM'}


def yaml_keys(text):
    keys, stack = set(), []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(('#', '-')):
            continue
        m = re.match(r'^(\s*)([\w.\-\[\]"\']+)\s*:', line)
        if not m:
            continue
        ind = len(m.group(1).expandtabs(2))
        while stack and stack[-1][0] >= ind:
            stack.pop()
        k = m.group(2).strip('"\'')
        stack.append((ind, k))
        keys.add('.'.join(s[1] for s in stack))
    return keys


def config_consistency(texts, doc_text):
    env_used = defaultdict(list)
    spring_used = defaultdict(list)
    defined = set()
    env_doc = set(re.findall(r'\b[A-Z][A-Z0-9_]{2,}\b', doc_text))
    for rel, t in texts.items():
        e = ext_of(rel)
        name = rel.rsplit('/', 1)[-1]
        if TEST_PATH.search(rel):
            continue
        is_sample = bool(re.search(r'example|sample|template', name, re.I))
        if e == '.env' or is_sample or 'compose' in name or name.lower().startswith('dockerfile') or e in {'.sh', '.bat', '.ps1'} or re.search(r'k8s|helm|deploy', rel, re.I):
            env_doc |= set(re.findall(r'\b([A-Z][A-Z0-9_]{2,})\s*[=:]', t)) | set(re.findall(r'\b(?:ENV|ARG|export)\s+([A-Z][A-Z0-9_]+)', t))
        if e in CODE:
            for rx in ENV_RE:
                for m in re.finditer(rx, t):
                    env_used[m.group(1)].append('%s:%d' % (rel, t.count('\n', 0, m.start()) + 1))
            if e in {'.java', '.kt'}:
                for m in re.finditer(r'@Value\(\s*"\$\{([\w.\-]+)(:[^}]*)?\}"', t):
                    if m.group(2) is None:
                        spring_used[m.group(1)].append('%s:%d' % (rel, t.count('\n', 0, m.start()) + 1))
        if re.search(r'(application|bootstrap)[^/]*\.(ya?ml|properties)$', name):
            if e == '.properties':
                defined |= set(re.findall(r'^\s*([\w.\-\[\]]+)\s*[=:]', t, re.M))
            else:
                defined |= yaml_keys(t)
            for m in re.finditer(ENV_IN_CONF, t):
                if m.group(2) is None:
                    env_used[m.group(1)].append('%s:%d' % (rel, t.count('\n', 0, m.start()) + 1))
    env_missing = {k: v[:5] for k, v in sorted(env_used.items()) if k not in env_doc and k not in ENV_COMMON and not k.startswith('npm_')}
    relaxed = {re.sub(r'[-_]', '', k.lower()) for k in defined}
    spring_missing = {k: v[:5] for k, v in sorted(spring_used.items()) if re.sub(r'[-_]', '', k.lower()) not in relaxed}
    return {'envUsed': sorted(env_used), 'envUndocumented': env_missing, 'springUndefined': spring_missing if defined else {}}


# ---------------- 结构指标 ----------------
FUNC_HEAD = {
    'brace': re.compile(r'^\s*(?:(?:public|private|protected|static|final|async|override|virtual|synchronized|export|default|func)\s+)*(?:[\w<>\[\],.?]+\s+)?(?:function\s+)?([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?::\s*[\w<>\[\]|, .]+)?\s*(?:throws\s+[\w.,\s]+)?\{\s*$'),
    'go': re.compile(r'^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\('),
}
NOT_FUNC = {'if', 'for', 'while', 'switch', 'catch', 'with', 'return', 'else', 'try', 'do', 'synchronized', 'foreach', 'using', 'lock'}


def long_functions(rel, lines, limit=150):
    out = []
    e = ext_of(rel)
    if e == '.py':
        i = 0
        while i < len(lines):
            m = re.match(r'^(\s*)(?:async\s+)?def\s+(\w+)', lines[i])
            if m:
                ind = len(m.group(1))
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
                    j += 1
                if j - i > limit:
                    out.append({'file': rel, 'line': i + 1, 'name': m.group(2), 'lines': j - i})
            i += 1
        return out
    if e not in {'.java', '.kt', '.js', '.ts', '.jsx', '.tsx', '.vue', '.go', '.cs', '.php', '.mjs'}:
        return out
    rx = FUNC_HEAD['go'] if e == '.go' else FUNC_HEAD['brace']
    for i, line in enumerate(lines):
        m = rx.match(line)
        if not m or m.group(1) in NOT_FUNC:
            continue
        depth, started, j = 0, False, i
        while j < len(lines) and j - i < 3000:
            c = re.sub(r'(["\'`])(?:\\.|(?!\1).)*\1', '', lines[j])
            depth += c.count('{') - c.count('}')
            if c.count('{'):
                started = True
            if started and depth <= 0:
                break
            j += 1
        if j - i + 1 > limit:
            out.append({'file': rel, 'line': i + 1, 'name': m.group(1), 'lines': j - i + 1})
    return out


def duplicates(code_texts, window=10):
    seen = defaultdict(list)
    for rel, lines in code_texts.items():
        norm = []
        for i, l in enumerate(lines):
            s = re.sub(r'\s+', '', l)
            if len(s) < 5 or re.match(r'^(import|from|package|#include|using|//|/\*|\*|@)', s):
                continue
            norm.append((i + 1, s))
        for k in range(0, len(norm) - window + 1):
            h = hashlib.md5('\n'.join(x[1] for x in norm[k:k + window]).encode()).hexdigest()[:16]
            seen[h].append((rel, norm[k][0]))
    pairs = defaultdict(list)
    for h, occ in seen.items():
        if 2 <= len(occ) <= 20:
            for a in range(len(occ)):
                for b in range(a + 1, len(occ)):
                    if occ[a][0] == occ[b][0] and abs(occ[a][1] - occ[b][1]) < window:
                        continue
                    pairs[(occ[a][0], occ[b][0])].append((occ[a][1], occ[b][1]))
    out = []
    for (fa, fb), lst in pairs.items():
        lst.sort()
        out.append({'a': fa, 'aLine': lst[0][0], 'b': fb, 'bLine': lst[0][1], 'approxLines': len(lst) + window - 1})
    out.sort(key=lambda x: -x['approxLines'])
    return out[:30]


# ---------------- 外部工具 ----------------
def run_gitleaks(root, outdir, has_git):
    exe = shutil.which('gitleaks')
    if not exe:
        return None, []
    res = {'tool': 'gitleaks', 'runs': []}
    hits = []
    modes = [('dir', [exe, 'dir', str(root)])]
    if has_git:
        modes.append(('git', [exe, 'git', str(root)]))
    for mode, cmd in modes:
        rep = Path(outdir) / ('gitleaks-%s.json' % mode)
        try:
            subprocess.run(cmd + ['--redact', '--no-banner', '-l', 'error', '--exit-code', '0', '-f', 'json', '-r', str(rep)],
                           capture_output=True, text=True, timeout=600)
            data = json.loads(rep.read_text(encoding='utf-8') or '[]')
            rep.unlink()
        except Exception as ex:
            res['runs'].append({'mode': mode, 'error': str(ex)[:200]})
            continue
        res['runs'].append({'mode': mode, 'found': len(data)})
        for d in data:
            f = os.path.relpath(d.get('File', ''), root).replace('\\', '/') if os.path.isabs(d.get('File', '')) else d.get('File', '')
            title = '历史提交里有密钥（文件删了也能从历史翻出来）' if mode == 'git' else '密钥扫描工具发现疑似密钥'
            hits.append({'rule': 'SEC-GITLEAKS' + ('-HISTORY' if mode == 'git' else ''), 'dim': D_SEC, 'level': '高', 'title': title,
                         'file': f, 'line': d.get('StartLine', 0), 'code': mask((d.get('Match') or '')[:160]) + ('（提交 %s）' % d.get('Commit', '')[:8] if mode == 'git' else ''),
                         'advice': '确认是真实密钥就作废换新，并从代码里移走（gitleaks 规则：%s）' % d.get('RuleID', '')})
    return res, hits


def run_npm_audit(root, files):
    if not shutil.which('npm'):
        return None
    out = []
    for f in files:
        if f.endswith('package-lock.json') and 'node_modules' not in f:
            d = (Path(root) / f).parent
            try:
                r = subprocess.run(['npm', 'audit', '--json', '--omit=dev'], cwd=str(d), capture_output=True, text=True, timeout=180)
                data = json.loads(r.stdout or '{}')
                v = (data.get('metadata') or {}).get('vulnerabilities') or {}
                top = []
                for name, info in (data.get('vulnerabilities') or {}).items():
                    if info.get('severity') in ('critical', 'high') and info.get('isDirect'):
                        top.append({'name': name, 'severity': info.get('severity'), 'range': info.get('range'), 'fix': bool(info.get('fixAvailable'))})
                out.append({'dir': str(Path(f).parent).replace('\\', '/'), 'counts': v, 'directHigh': top[:30]})
            except Exception as ex:
                out.append({'dir': str(Path(f).parent), 'error': str(ex)[:200]})
    return out


# ---------------- 主流程 ----------------
def hit_id(rule, rel, code):
    return 'S-' + hashlib.md5(('%s|%s|%s' % (rule, rel, re.sub(r'\s+', '', code))).encode()).hexdigest()[:6]


def scan(root, outdir, since=None, excludes=(), tools=True, online=False, per_file_cap=8):
    root = Path(root).resolve()
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    ex = set(e.strip('/').replace('\\', '/') for e in excludes)
    try:
        ex.add(str(outdir.relative_to(root)).replace('\\', '/'))
    except ValueError:
        pass
    files, junk = walk(root, ex)
    has_git = (root / '.git').exists()
    tracked = set((git(root, 'ls-files') or '').splitlines()) if has_git else None
    changed = None
    if since and has_git:
        changed = set((git(root, 'diff', '--name-only', since + '...HEAD') or '').splitlines()) | set((git(root, 'diff', '--name-only') or '').splitlines())

    hits, texts, code_lines = [], {}, {}
    lang_stat = Counter()
    lang_files = Counter()
    big_files, long_files, long_funcs = [], [], []
    overflow = Counter()
    for rel in files:
        p = root / rel
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > 10 * 1024 * 1024:
            big_files.append({'file': rel, 'mb': round(size / 1048576, 1)})
        e = ext_of(rel)
        if e not in LANG and e not in {'.yml', '.yaml', '.properties', '.env', '.ini', '.conf', '.cfg', '.toml', '.xml', '.json', 'dockerfile', '.md', '.txt'}:
            continue
        if SKIP_FILE.search(rel):
            continue
        t = read_text(p)
        if t is None:
            continue
        lines = t.splitlines()
        if lines and len(t) / max(len(lines), 1) > 300 and e in {'.js', '.css', '.json'}:
            continue   # 压缩过的
        texts[rel] = t
        if e in LANG:
            lang_stat[LANG[e]] += len(lines)
            lang_files[LANG[e]] += 1
        if e in CODE:
            code_lines[rel] = lines
            if len(lines) > 1000:
                long_files.append({'file': rel, 'lines': len(lines)})
            long_funcs += long_functions(rel, lines)
        if changed is not None and rel not in changed:
            continue
        in_test = bool(TEST_PATH.search(rel))
        vendor = bool(VENDOR_PATH.search(rel))
        for r in RULES:
            if e not in r.exts or (in_test and not r.in_tests) or (vendor and not r.secret):
                continue
            if r.file_has and not r.file_has.search(t):
                continue
            n = 0
            if r.multiline:
                for m in r.re.finditer(t):
                    ln = t.count('\n', 0, m.start()) + 1
                    code = lines[ln - 1].strip() if ln - 1 < len(lines) else m.group(0)
                    n += 1
                    if n > per_file_cap:
                        overflow[(r.id, rel)] += 1
                        continue
                    hits.append({'rule': r.id, 'dim': r.dim, 'level': r.level, 'title': r.title, 'file': rel, 'line': ln,
                                 'code': code[:200], 'advice': r.advice, 'inTest': in_test})
                continue
            for i, line in enumerate(lines):
                if len(line) > 1000:
                    continue
                if r.code_only and COMMENT_LINE.match(line):
                    continue
                m = r.re.search(line)
                if not m:
                    continue
                if r.skip_if and r.skip_if.search(line):
                    continue
                if r.filter and not r.filter(m):
                    continue
                n += 1
                if n > per_file_cap:
                    overflow[(r.id, rel)] += 1
                    continue
                level = '高' if (r.escalate and r.escalate.search(line) and r.level in ('中', '低')) else r.level
                code = line.strip()[:200]
                hits.append({'rule': r.id, 'dim': r.dim, 'level': level, 'title': r.title, 'file': rel, 'line': i + 1,
                             'code': mask(code) if r.secret else code, 'advice': r.advice, 'inTest': in_test})

    # 不该进源码包的文件
    for rel in files:
        if SECRET_FILE.search(rel) and not SECRET_FILE_OK.search(rel) and (tracked is None or rel in tracked):
            hits.append({'rule': 'SEC-SECRET-FILE', 'dim': D_SEC, 'level': '高', 'title': '密钥或生产配置文件放进了代码库',
                         'file': rel, 'line': 0, 'code': '', 'advice': '移出代码库并加进 .gitignore；里面的口令和密钥换新。', 'inTest': False})
    junk_tracked = []
    if tracked is not None:
        for d in JUNK_DIRS:
            if any(t.startswith(d + '/') or ('/' + d + '/') in t for t in tracked):
                junk_tracked.append(d)
        jars = [t for t in tracked if t.endswith(('.jar', '.class', '.war', '.pyc', '.exe', '.dll')) and 'wrapper' not in t]
        if jars:
            junk_tracked.append('编译产物（%s 等 %d 个）' % (jars[0], len(jars)))
    else:
        junk_tracked = [j for j in junk if j.split('/')[-1] in JUNK_DIRS]
    if junk_tracked:
        hits.append({'rule': 'STYLE-JUNK-FILES', 'dim': D_STYLE, 'level': '低', 'title': '源码里带了不该交的东西（依赖包、编译产物、编辑器配置）',
                     'file': '、'.join(junk_tracked[:6]), 'line': 0, 'code': '', 'advice': '从源码包里去掉，写进 .gitignore；依赖由构建时下载。', 'inTest': False})
    gi = root / '.gitignore'
    if has_git and not gi.exists():
        hits.append({'rule': 'STYLE-NO-GITIGNORE', 'dim': D_STYLE, 'level': '低', 'title': '没有 .gitignore', 'file': '', 'line': 0, 'code': '',
                     'advice': '加 .gitignore，至少排除依赖目录、编译产物、.env 和日志。', 'inTest': False})
    dockerfiles = [f for f in texts if ext_of(f) == 'dockerfile']
    for f in dockerfiles:
        if not re.search(r'^\s*USER\s+', texts[f], re.M | re.I):
            hits.append({'rule': 'OPS-DOCKER-ROOT', 'dim': '运维', 'level': '低', 'title': '容器用 root 身份运行', 'file': f, 'line': 0, 'code': '',
                         'advice': '加一个普通用户，用 USER 切过去运行。', 'inTest': False})

    # 依赖
    dep_list, risky, scripts = depmod.collect(files, root)
    for d in risky:
        if d['level'] == '待核':
            continue
        hits.append({'rule': 'DEP-KNOWN-VULN', 'dim': D_DEP, 'level': d['level'], 'title': '用了有已知漏洞的组件版本：%s %s' % (d['name'], d['version']),
                     'file': d['file'], 'line': 0, 'code': '%s %s' % (d['name'], d['spec']),
                     'advice': d['desc'] + ('；升级到 %s 或更高' % d['fixed'] if d.get('fixed') else '') + ('（只看了声明的最低版本，实际装的可能更高，以锁定文件为准）' if d.get('approx') else ''),
                     'inTest': False})
    stack = detect_stack(files, root, dep_list)

    # 测试
    src = [f for f in code_lines if not TEST_PATH.search(f)]
    tst = [f for f in code_lines if TEST_PATH.search(f)]
    tests = {'srcFiles': len(src), 'testFiles': len(tst), 'sample': tst[:15],
             'npmTest': scripts.get('test', '')}
    if tests['npmTest'] and 'no test specified' in tests['npmTest']:
        tests['npmTest'] = '（默认占位，没有测试）'
    if len(src) >= 10 and len(tst) == 0:
        hits.append({'rule': 'TEST-NONE', 'dim': D_TEST, 'level': '中', 'title': '没有任何自动化测试', 'file': '', 'line': 0, 'code': '',
                     'advice': '至少给核心业务规则（金额、状态流转、权限）补接口或单元测试，改代码后能回归。', 'inTest': False})

    docs = classify_docs(files, root)
    deliverables, doc_text = assess_deliverables(files, root, docs, stack, tests, scripts, junk_tracked)
    cons = config_consistency(texts, doc_text + '\n'.join(t for r, t in texts.items() if ext_of(r) in {'.md', '.txt'}))
    for k, locs in cons['envUndocumented'].items():
        hits.append({'rule': 'DELIV-ENV-UNDOC', 'dim': D_DELIV, 'level': '中', 'title': '程序要读的配置项文档里没写：%s' % k, 'file': locs[0].rsplit(':', 1)[0],
                     'line': int(locs[0].rsplit(':', 1)[1]), 'code': k, 'advice': '在部署手册和配置样例里写明这个配置项的含义、取值和是否必填。', 'inTest': False})
    for k, locs in cons['springUndefined'].items():
        hits.append({'rule': 'BUG-CONF-UNDEFINED', 'dim': D_BUG, 'level': '中', 'title': '代码要读的配置项在配置文件里没定义：%s' % k, 'file': locs[0].rsplit(':', 1)[0],
                     'line': int(locs[0].rsplit(':', 1)[1]), 'code': k, 'advice': '没有默认值时程序启动会失败：在配置文件里补上，或给 @Value 写默认值。', 'inTest': False})

    for f in long_files:
        hits.append({'rule': 'REASON-LONG-FILE', 'dim': D_REASON, 'level': '低', 'title': '单个文件太长（%d 行），难维护' % f['lines'], 'file': f['file'], 'line': 0, 'code': '',
                     'advice': '按职责拆分。', 'inTest': False})
    for f in long_funcs:
        hits.append({'rule': 'REASON-LONG-FUNC', 'dim': D_REASON, 'level': '低', 'title': '函数太长（约 %d 行）：%s' % (f['lines'], f['name']), 'file': f['file'], 'line': f['line'], 'code': '',
                     'advice': '拆成几个职责单一的小函数，便于测试。', 'inTest': False})
    dups = duplicates({k: v for k, v in code_lines.items() if not TEST_PATH.search(k)}) if len(code_lines) < 5000 else []
    for d in dups[:15]:
        if d['approxLines'] >= 15:
            hits.append({'rule': 'REASON-DUPLICATE', 'dim': D_REASON, 'level': '低', 'title': '大段重复代码（约 %d 行）' % d['approxLines'], 'file': d['a'], 'line': d['aLine'],
                         'code': '与 %s:%d 重复' % (d['b'], d['bLine']), 'advice': '抽成公共方法；改一处忘改另一处是常见缺陷来源。', 'inTest': False})

    tool_res = {}
    if tools:
        gl, gl_hits = run_gitleaks(root, outdir, has_git)
        if gl:
            tool_res['gitleaks'] = gl
            hits += gl_hits
        if online:
            na = run_npm_audit(root, files)
            if na is not None:
                tool_res['npmAudit'] = na

    seen_ids = set()
    for h in hits:
        hid = hit_id(h['rule'], h['file'], h['code'] or h['title'])
        while hid in seen_ids:
            hid = hid + 'x'
        seen_ids.add(hid)
        h['id'] = hid

    gitinfo = None
    if has_git:
        log = git(root, 'log', '-1', '--format=%h %ci %s')
        cnt = git(root, 'rev-list', '--count', 'HEAD')
        gitinfo = {'last': (log or '').strip(), 'commits': (cnt or '').strip(), 'branch': (git(root, 'rev-parse', '--abbrev-ref', 'HEAD') or '').strip(),
                   'dirty': bool((git(root, 'status', '--porcelain') or '').strip()), 'since': since or ''}

    result = {
        'version': 1,
        'scannedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'root': str(root),
        'project': root.name,
        'git': gitinfo,
        'files': len(files),
        'languages': [{'lang': k, 'files': lang_files[k], 'lines': v} for k, v in lang_stat.most_common()],
        'stack': stack,
        'deps': {'count': len(dep_list), 'risky': risky, 'list': dep_list[:500]},
        'tests': tests,
        'deliverables': deliverables,
        'config': cons,
        'duplicates': dups,
        'longFunctions': sorted(long_funcs, key=lambda x: -x['lines'])[:30],
        'bigFiles': big_files,
        'tools': tool_res,
        'overflow': [{'rule': k[0], 'file': k[1], 'more': v} for k, v in overflow.items()],
        'hits': hits,
    }
    (outdir / 'scan.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    return result
