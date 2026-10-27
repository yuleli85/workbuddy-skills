"""自动扫描规则：逐行匹配的写法问题、密钥、配置风险。

每条规则命中的只是「疑点」，要人（或 AI）打开代码核对后才算问题。
"""
import re

# 文件分组（按扩展名）
JAVA = {'.java', '.kt', '.scala', '.groovy'}
JS = {'.js', '.jsx', '.ts', '.tsx', '.vue', '.mjs', '.cjs', '.nvue', '.svelte'}
PY = {'.py'}
PHP = {'.php'}
GO = {'.go'}
CS = {'.cs'}
TPL = {'.html', '.htm', '.jsp', '.ftl', '.vm', '.jinja', '.jinja2', '.j2', '.ejs', '.hbs', '.twig', '.wxml'}
CONF = {'.yml', '.yaml', '.properties', '.env', '.ini', '.conf', '.cfg', '.toml', '.xml', '.json'}
SQL = {'.sql'}
SH = {'.sh', '.bash', '.ps1', '.bat', '.cmd'}
CODE = JAVA | JS | PY | PHP | GO | CS | {'.rb', '.c', '.cpp', '.h', '.rs', '.swift', '.dart', '.m'}
ALL_TEXT = CODE | TPL | CONF | SQL | SH | {'dockerfile'}

# 维度
D_FUNC, D_BUG, D_SEC, D_REASON, D_DELIV, D_DEP, D_COMP, D_OPS, D_TEST, D_STYLE = (
    '功能', '缺陷', '安全', '合理性', '交付物', '依赖', '合规', '运维', '测试', '规范')

EXT_IN = r'(request\.|req\.(query|params|body)|getParameter|\$_(GET|POST|REQUEST|COOKIE)|args\.get|form\.get|params\[|@RequestParam|ctx\.(query|params|request))'


class Rule:
    def __init__(self, id, dim, level, title, exts, pattern, advice,
                 flags=0, skip_if=None, escalate=None, code_only=True,
                 file_has=None, secret=False, in_tests=False, multiline=False, filter=None):
        self.id = id
        self.dim = dim
        self.level = level
        self.title = title
        self.exts = exts
        self.re = re.compile(pattern, flags | (re.M if multiline else 0))
        self.advice = advice
        self.skip_if = re.compile(skip_if, re.I) if skip_if else None
        self.escalate = re.compile(escalate, re.I) if escalate else None  # 同一行再命中就升为「高」
        self.code_only = code_only      # True：跳过注释行
        self.file_has = re.compile(file_has) if file_has else None  # 文件内容要先含这个才查
        self.secret = secret            # 命中内容要打码
        self.in_tests = in_tests        # 测试代码里也查
        self.multiline = multiline      # 对全文匹配（跨行）
        self.filter = filter            # 额外判断函数 (match) -> bool


PLACEHOLDER = re.compile(
    r'^(\*+|x+|\.+|-+|your.*|change.*|example.*|placeholder|todo|tbd|none|null|nil|true|false|undefined|'
    r'password|passwd|secret|token|test|demo|sample|string|required|optional|\[.*\]|<.*>|%\(.*)$', re.I)


SECRET_SUFFIX_OK = {'', 'key', 'keys', 'secret', 'value', 'val', 'str', 'string', 'salt', 'hash', 'pwd', 'plain', 'raw',
                    'b64', 'base64', 'enc', 'encrypted', 'cipher', 'id', 'keyid', 'secretkey', 'accesskey', 'pass', 'word'}


def _real_secret(m):
    v = (m.group('v') or '').strip().strip('"\'')
    if len(v) < 6 or PLACEHOLDER.match(v):
        return False
    suf = re.sub(r'[_\-.]', '', (m.groupdict().get('suf') or '')).lower()
    if suf not in SECRET_SUFFIX_OK:
        return False      # passwordRequired、max_tokens 这类是提示语或参数名
    if re.search(r'[^\x00-\x7f]', v) or re.fullmatch(r'[\d.]+', v) or re.fullmatch(r'@[\w.\-]+@', v):
        return False      # 中文提示语、纯数字、Maven 占位符
    if any(s in v for s in ('${', '{{', '#{', 'process.env', 'os.environ', 'getenv', 'System.getenv', 'import.meta')):
        return False
    return True


def _real_secret_code(m):
    if not _real_secret(m):
        return False
    v = m.group('v')
    # 代码里像「Admin-Token」「Authorization」这类纯单词多半是键名，不是密钥
    if re.fullmatch(r'[A-Za-z][A-Za-z_\-]*', v) and len(v) <= 24:
        return False
    if re.fullmatch(r'[\w.\-]+\.(png|jpg|svg|js|css|html)', v, re.I):
        return False
    return True


RULES = [
    # ---------------- 安全：密钥和口令 ----------------
    Rule('SEC-PRIVATE-KEY', D_SEC, '严重', '代码里放了私钥', ALL_TEXT,
         r'-----BEGIN (RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY',
         '私钥移出代码库，放到服务器的密钥文件或密钥管理服务；已经提交过的视为泄露，要换新的。',
         code_only=False, secret=True, in_tests=True),
    Rule('SEC-CLOUD-AK', D_SEC, '严重', '代码里放了云服务访问密钥', ALL_TEXT,
         r'\b(AKIA[0-9A-Z]{16}|LTAI[0-9A-Za-z]{12,24}|AKID[0-9A-Za-z]{13,40})\b',
         '云账号密钥一旦进代码库就当已泄露：马上到云控制台作废并换新，新密钥用环境变量或密钥管理服务注入。',
         code_only=False, secret=True, in_tests=True),
    Rule('SEC-HARDCODED-SECRET', D_SEC, '高', '口令或密钥写死在代码里', CODE | TPL,
         r'(?i)\b[\w.\-]*(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|app[_-]?secret|private[_-]?key|credential|signkey|sign[_-]?key|jwt[_-]?key)(?P<suf>[\w\-]*)["\']?\s*[:=]{1,2}\s*["\'](?P<v>[^"\'\s]{6,})["\']',
         '改成从环境变量或配置中心读取，代码和仓库里只留示例值；已提交过的真实口令要换掉。',
         code_only=False, secret=True, in_tests=True, filter=_real_secret_code,
         skip_if=r'(getenv|environ|process\.env|@Value|placeholder|example|\$\{)'),
    Rule('SEC-CONF-SECRET', D_SEC, '高', '配置文件里写了真实口令或密钥', CONF - {'.json'},
         r'(?i)^\s*[\w.\-]*(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|app[_-]?secret|private[_-]?key|credential)(?P<suf>[\w\-]*)\s*[:=]\s*["\']?(?P<v>[^\s"\'#]{4,})',
         '生产口令不要进代码库：配置里写成 ${环境变量} 引用，部署手册写清要设哪些变量；已提交过的要换掉。',
         code_only=False, secret=True, in_tests=True, filter=_real_secret,
         skip_if=r'(\.example|sample|^\s*#)'),
    Rule('SEC-XML-SECRET', D_SEC, '高', '配置文件里写了真实口令或密钥', {'.xml'},
         r'(?i)<(?P<k>[\w.\-]*(password|secret|token|accesskey|apikey)[\w.\-]*)>(?P<v>[^<${]{4,})</',
         '同上：改成占位引用，真实值部署时注入。', code_only=False, secret=True, filter=_real_secret),
    Rule('SEC-CONN-PASSWORD', D_SEC, '高', '连接串里带了口令', ALL_TEXT,
         r'(?i)(jdbc:[^\s"\']*(password|pwd)=[^&\s"\';$]{3,}|(mysql|postgres(ql)?|mongodb(\+srv)?|redis|amqp|ftp)://[^:/\s"\'@]+:[^@/\s"\'$]{3,}@)',
         '连接串里的口令拿出来放环境变量；已提交过的要换掉。', code_only=False, secret=True, in_tests=True),
    Rule('SEC-DEFAULT-PASSWORD', D_SEC, '高', '弱口令或默认口令', ALL_TEXT,
         r'(?i)(password|passwd|pwd|口令|密码)["\']?\s*[:=：]\s*["\']?(123456|12345678|admin|admin123|root|111111|888888|000000|qwerty|abc123)\b',
         '默认口令要求首次登录强制修改；生产环境的初始化数据不能带弱口令。', code_only=False, secret=True),

    # ---------------- 安全：注入 ----------------
    Rule('SEC-SQL-CONCAT', D_SEC, '高', 'SQL 用字符串拼接，可能被注入', JAVA | JS | PHP | CS | GO,
         r'(?i)["\'][^"\']*\b(select|insert\s+into|update|delete\s+from|where|order\s+by|group\s+by|values|and|or)\b[^"\']*["\']\s*\+\s*[A-Za-z_$(]',
         '改用参数化查询（预编译占位符 ? / #{} / :name）；排序字段这类不能参数化的，用白名单校验。',
         skip_if=r'(log\.|logger\.|console\.|throw|Exception|message|msg|title|label|placeholder|\.append\("\s*"\))',
         escalate=EXT_IN),
    Rule('SEC-SQL-FORMAT', D_SEC, '高', 'SQL 用字符串格式化拼参数，可能被注入', PY,
         r'(?i)(\.(execute|executemany|raw|text|exec_driver_sql)\(\s*(f["\']|["\'][^"\']*["\']\s*(%|\.format\())|\bf["\']\s*(select|insert\s+into|update|delete\s+from)\b[^"\']*\{)',
         '改用参数化：cursor.execute("... where id=%s", (id,)) 或 ORM 查询；不要用 f-string / % / format 拼 SQL。'),
    Rule('SEC-SQL-TEMPLATE', D_SEC, '高', 'SQL 用模板字符串拼参数，可能被注入', JS,
         r'(?i)(`\s*(select|insert\s+into|update|delete\s+from)\b[^`]*\$\{|\b(query|execute|raw)\s*\(\s*`[^`]*\$\{)',
         '改用占位符参数：db.query("... where id = ?", [id])；ORM 的 raw 查询同样要用 replacements/bind。'),
    Rule('SEC-SQL-SPRINTF', D_SEC, '高', 'SQL 用格式化函数拼参数，可能被注入', GO | JAVA | CS,
         r'(?i)(fmt\.Sprintf|String\.format|string\.Format)\(\s*[@$]?["`]\s*(select|insert\s+into|update|delete\s+from)\b[^"`]*(%[sdv]|\{\d)',
         '改用占位符参数：db.Query("... where id = ?", id)、PreparedStatement、SqlParameter；不要用 Sprintf / String.format 拼 SQL。'),
    Rule('SEC-MYBATIS-DOLLAR', D_SEC, '高', 'MyBatis 用了 ${} 直接拼 SQL', {'.xml'} | JAVA,
         r'\$\{[^}]+\}',
         '把 ${} 改成 #{}；表名、排序字段等不能用 #{} 的，在代码里用白名单校验后再传。',
         file_has=r'(<mapper|@Select|@Update|@Delete|@Insert)',
         skip_if=r'(@Value|<property|\$\{(jdbc|spring|project|env)\.)'),
    Rule('SEC-CMD-EXEC', D_SEC, '高', '执行系统命令，参数来自外部时可被命令注入', JAVA | PY | PHP | GO | CS | JS,
         r'(Runtime\.getRuntime\(\)\.exec\(|new\s+ProcessBuilder\(|\bos\.(system|popen)\(|subprocess\.\w+\([^)]*shell\s*=\s*True|\b(shell_exec|passthru|proc_open|popen)\s*\(|(?<![\w.>])system\s*\(\s*\$|\bexec\.Command\(|Process\.Start\(|\bexecSync\(|child_process[\'"]?\)?\.exec\(|\bexec\(\s*`[^`]*\$\{)',
         '能不调命令就用对应的程序库；必须调的，参数用列表传（不经过 shell），外部输入严格白名单。',
         escalate=EXT_IN),
    Rule('SEC-EVAL', D_SEC, '高', '动态执行代码（eval 一类）', JS | PY | PHP,
         r'((?<![\w.])eval\s*\(|new\s+Function\s*\(|(?<![\w.])exec\s*\(\s*(?!["\']\s*\))|\bassert\s*\(\s*\$)',
         '去掉 eval/exec；要解析数据用 JSON.parse / json.loads / ast.literal_eval。',
         skip_if=r'(\.exec\(|re\.|regex|RegExp|pattern|//\s*eslint)'),
    Rule('SEC-DESERIALIZE', D_SEC, '高', '反序列化不可信数据，可能被远程执行代码', JAVA | PY | PHP | JS,
         r'(new\s+ObjectInputStream\(|new\s+XMLDecoder\(|setAutoTypeSupport\(\s*true|Feature\.SupportAutoType|enableDefaultTyping\(|activateDefaultTyping\(|\bpickle\.loads?\(|\bcPickle\b|\bmarshal\.loads\(|yaml\.unsafe_load\(|yaml\.load\((?![^)]*Loader\s*=\s*(yaml\.)?(Safe|CSafe|Base)Loader)|(?<![\w>])unserialize\s*\(|require\([\'"]node-serialize)',
         '外部来的数据只用 JSON 这类纯数据格式；YAML 用 safe_load；fastjson 关掉 autoType 或换 fastjson2。'),
    Rule('SEC-XSS', D_SEC, '中', '把内容当网页代码直接插入页面，可能跨站脚本', JS | TPL,
         r'(\.innerHTML\s*[+]?=(?!\s*(""|\'\'|``)\s*;?\s*$)|\bv-html\s*=|dangerouslySetInnerHTML|document\.write\(|\.outerHTML\s*=|insertAdjacentHTML\(|\|\s*safe\b|th:utext|<%-|\{\{\{|autoescape\s+false|\bMarkup\(|rich-text[^>]*nodes)',
         '显示用户可编辑的内容时先转义或用白名单清洗（如 DOMPurify）；能用文本绑定的不用 HTML 绑定。'),
    Rule('SEC-XSS-ECHO', D_SEC, '高', '把请求参数原样输出到页面', PHP | JAVA,
         r'(echo\s+\$_(GET|POST|REQUEST|COOKIE)|getWriter\(\)\.(print|write)\w*\([^)]*getParameter)',
         '输出前用 htmlspecialchars / 模板引擎转义。'),
    Rule('SEC-PATH-TRAVERSAL', D_SEC, '高', '用外部传入的路径读写文件，可能越目录', CODE,
         r'(?i)(new\s+File\(|Paths\.get\(|Path\.of\(|FileInputStream\(|FileOutputStream\(|\bopen\(|readFile(Sync)?\(|writeFile(Sync)?\(|sendFile\(|createReadStream\(|send_file\(|send_from_directory\(|file_get_contents\(|unlink\(|os\.remove\(|Files\.\w+\()[^;\n]*' + EXT_IN,
         '文件名只接受编号或白名单字符，拼出路径后校验仍在允许的目录里（规范化后比对前缀）。'),
    Rule('SEC-UPLOAD-NAME', D_SEC, '中', '上传文件直接用原文件名，没看到类型和大小校验', CODE,
         r'(getOriginalFilename\(\)|\.originalname\b|\.save\([^)]*\.filename|file\.filename\b)',
         '保存时用服务端生成的文件名；校验扩展名和内容类型白名单、限制大小；上传目录不能执行脚本。',
         skip_if=r'secure_filename'),
    Rule('SEC-SSRF', D_SEC, '中', '服务端按外部传入的地址发请求，可能被利用访问内网', CODE,
         r'(?i)(requests\.(get|post|request)\(|urlopen\(|new\s+URL\(|RestTemplate|\.getForObject\(|\.postForObject\(|HttpClient|axios(\.(get|post))?\(|\bfetch\(|http\.(get|request)\(|curl_init\()[^;\n]*' + EXT_IN,
         '目标地址用白名单；禁止访问内网和云服务器元数据地址。'),
    Rule('SEC-OPEN-REDIRECT', D_SEC, '中', '跳转地址来自外部参数，可能被用来钓鱼', CODE,
         r'(?i)(sendRedirect\(|\bredirect\(|res\.redirect\(|header\(\s*["\']Location)[^;\n]*' + EXT_IN,
         '只允许跳到本站路径或白名单域名。'),
    Rule('SEC-WEAK-HASH', D_SEC, '中', '用了 MD5/SHA1（用于存口令就是高危）', CODE,
         r'(?i)(DigestUtils\.(md5|sha1)|MessageDigest\.getInstance\(\s*"(MD5|SHA-?1)"|hashlib\.(md5|sha1)\(|createHash\(\s*[\'"](md5|sha1)[\'"]|SecureUtil\.(md5|sha1)|DigestUtil\.(md5|sha1)|\bmd5\s*\(|\bsha1\s*\(|Md5Crypt|Md5Utils)',
         '存口令改用 bcrypt / argon2 / PBKDF2（加盐、慢哈希）；只做文件校验、缓存键的可忽略。',
         escalate=r'(pass|pwd|口令|密码)'),
    Rule('SEC-WEAK-CRYPTO', D_SEC, '中', '加密算法或模式不安全（DES/RC4/ECB）', CODE,
         r'(Cipher\.getInstance\(\s*"(AES|DES|DESede|RC4|Blowfish)"\s*\)|Cipher\.getInstance\(\s*"[^"]*/ECB/|AES\.MODE_ECB|crypto\.createCipher\(|[\'"](aes-\d+-ecb|des|des-ede3|des-cbc|rc4)[\'"]|mode\s*:\s*CryptoJS\.mode\.ECB|CryptoJS\.(DES|TripleDES|RC4))',
         '改用 AES-GCM（或 AES-CBC 加随机 IV 再加签名）；密钥不要写在代码里。'),
    Rule('SEC-WEAK-RANDOM', D_SEC, '中', '验证码、令牌用了可预测的随机数', CODE,
         r'(?i)(Math\.random\(\)|new\s+Random\(|\brandom\.(randint|random|choice|choices|randrange)\(|\brand\(|mt_rand\()',
         '安全相关的随机数用 SecureRandom / secrets / crypto.randomBytes / random_bytes。'),
    Rule('SEC-TLS-OFF', D_SEC, '中', '关掉了证书校验，传输可被中间人截获', CODE | CONF,
         r'(verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED|InsecureSkipVerify\s*:\s*true|ALLOW_ALL_HOSTNAME_VERIFIER|NoopHostnameVerifier|TrustAllStrategy|TrustSelfSignedStrategy|trustAllCerts|CURLOPT_SSL_VERIFY(PEER|HOST)\s*,\s*(false|0)|ssl\._create_unverified_context|CERT_NONE)',
         '恢复证书校验；内部自签证书把根证书加进信任列表，不要整体关掉。'),
    Rule('SEC-CORS-ANY', D_SEC, '中', '跨域放开给所有网站', CODE | CONF,
         r'(Access-Control-Allow-Origin["\']?\s*[,:]\s*["\']\*|allowedOrigins\(\s*"\*"|allowedOriginPatterns\(\s*"\*"|addAllowedOrigin\(\s*"\*"|addAllowedOriginPattern\(\s*"\*"|@CrossOrigin\s*(\(\s*\))?\s*$|origin\s*:\s*(true|[\'"]\*[\'"])|CORS_ORIGIN_ALLOW_ALL\s*=\s*True|CORS_ALLOW_ALL_ORIGINS\s*=\s*True|allow_origins\s*=\s*\[\s*["\']\*|allowed-origins\s*:\s*["\']?\*)',
         '只放开自己的前端域名；带登录凭据的请求更不能用 *。'),
    Rule('SEC-JWT-WEAK', D_SEC, '高', '令牌校验被关掉或允许 none 算法', CODE,
         r'(?i)(verify_signature["\']?\s*:\s*False|algorithms\s*=\s*\[\s*["\']none|jwt\.decode\([^)]*verify\s*=\s*False|parseUnsecuredClaims|\.decode\(\s*\w+\s*\)\s*;?\s*//.*jwt|ignoreExpiration\s*:\s*true|alg["\']?\s*:\s*["\']none)',
         '令牌必须校验签名和过期时间，固定允许的算法。'),
    Rule('SEC-DEBUG-ON', D_SEC, '中', '调试开关或管理端点对外开着', CODE | CONF,
         r'(?i)(^\s*DEBUG\s*=\s*True|app\.run\([^)]*debug\s*=\s*True|exposure\.include\s*[=:]\s*["\']?\*|^\s*include\s*:\s*["\']\*["\']|h2\.console\.enabled\s*[=:]\s*true|knife4j\.production\s*[=:]\s*false|swagger\.enabled\s*[=:]\s*true|display_errors\s*=\s*On|APP_DEBUG\s*=\s*true|setDebug\(\s*true|devtools\s*:\s*true|login-username\s*:\s*admin)',
         '生产配置关掉调试、接口文档页和管理端点，或者至少加登录；部署手册写清生产配置怎么设。',
         code_only=False),
    Rule('SEC-LOG-SENSITIVE', D_COMP, '中', '日志或打印里输出了口令、令牌、身份证、手机号', CODE,
         r'(?i)(\blog(ger)?\.(info|debug|warn|warning|error|trace)\s*\(|console\.(log|info|debug|warn|error)\s*\(|\bprint(ln|f)?\s*\(|System\.(out|err)\.print\w*\s*\(|logging\.\w+\s*\()',
         '日志里去掉或打码这些字段（如手机号中间四位打星）；按个人信息保护要求，日志也算存储。'),

    # ---------------- 缺陷 ----------------
    Rule('BUG-JAVA-STR-EQ', D_BUG, '中', '字符串用 == 比较（应该用 equals）', JAVA,
         r'([\w)\]]\s*[!=]=\s*"[^"]*"|"[^"]*"\s*[!=]=\s*[\w(])',
         '改成 "常量".equals(变量) 或 Objects.equals(a, b)。', skip_if=r'^\s*(@|import)'),
    Rule('BUG-BIGDECIMAL-DOUBLE', D_BUG, '中', '用小数直接构造 BigDecimal，会带上浮点误差', JAVA,
         r'new\s+BigDecimal\(\s*(-?\d+\.\d+|\w*(double|Double|float)\w*)\s*\)',
         '改成 new BigDecimal("0.1") 或 BigDecimal.valueOf(x)。'),
    Rule('BUG-BIGDECIMAL-EQUALS', D_BUG, '低', 'BigDecimal 用 equals 比较（1.0 和 1.00 会不相等）', JAVA,
         r'(BigDecimal[^;]*\.equals\(|\.equals\(\s*BigDecimal\.)',
         '比大小、判相等用 compareTo(...) == 0。'),
    Rule('BUG-MONEY-FLOAT', D_BUG, '中', '金额用浮点数存或算，会有分厘误差', JAVA | CS | PY | JS | GO,
         r'(?i)(\b(double|float|Double|Float|float64|float32)\s+\w*(amount|price|money|fee|balance|pay|discount|金额)\w*|\bfloat\([^)]*(amount|price|money|fee|balance)|parseFloat\([^)]*(amount|price|money|fee|balance))',
         '金额用 BigDecimal / Decimal / 整数「分」存和算；数据库用 DECIMAL。'),
    Rule('BUG-STATIC-DATEFORMAT', D_BUG, '中', 'SimpleDateFormat 设成静态共用，多线程下会算错日期', JAVA,
         r'static\s+(final\s+)?(SimpleDateFormat|DateFormat)\b',
         '改用 DateTimeFormatter（线程安全），或每次新建。'),
    Rule('BUG-PY-MUTABLE-DEFAULT', D_BUG, '中', '函数默认参数用了可变对象，调用之间会互相串数据', PY,
         r'def\s+\w+\([^)]*=\s*(\[\]|\{\}|set\(\)|list\(\)|dict\(\))',
         '默认值写 None，函数里 if x is None: x = []。'),
    Rule('BUG-NAN-COMPARE', D_BUG, '中', '和 NaN 用等号比较，结果永远是假', JS,
         r'[=!]==?\s*NaN\b|\bNaN\s*[=!]==?',
         '改用 Number.isNaN(x)。'),
    Rule('BUG-ASSIGN-IN-IF', D_BUG, '中', '判断条件里写成了赋值（= 写成了 ==？）', JS | PHP,
         r'\bif\s*\(\s*[A-Za-z_$][\w.$\[\]\'"]*\s*=\s*(?![=>])[^)]*\)',
         '确认是否应为 === / ==。'),
    Rule('BUG-EMPTY-CATCH', D_BUG, '中', '出错后什么都不做（吞掉异常），问题会被藏起来', JAVA | JS | CS | PHP,
         r'catch\s*\([^)]*\)\s*\{\s*\}', '至少记日志；该往上抛的往上抛，该给用户提示的提示。',
         multiline=True),
    Rule('BUG-PY-EXCEPT-PASS', D_BUG, '中', '出错后什么都不做（吞掉异常），问题会被藏起来', PY,
         r'^\s*except[^:\n]*:\s*\n\s*pass\b', '至少记日志；只捕获能处理的异常类型。', multiline=True),
    Rule('BUG-PY-BARE-EXCEPT', D_REASON, '低', '捕获了所有异常（裸 except）', PY,
         r'^\s*except\s*:', '写明要捕获的异常类型；不要连 KeyboardInterrupt、SystemExit 一起捕获。'),
    Rule('BUG-UNCLOSED-STREAM', D_BUG, '低', '打开文件或流没用自动关闭的写法，出错时可能不关', JAVA,
         r'=\s*new\s+(FileInputStream|FileOutputStream|FileReader|FileWriter|BufferedReader|BufferedWriter|RandomAccessFile)\(',
         '改成 try (...) { } 自动关闭。', skip_if=r'try\s*\('),

    # ---------------- 功能完整性线索 ----------------
    Rule('FUNC-TODO', D_FUNC, '低', '留有「待完成」标记，对应功能可能没做完', CODE | TPL,
         r'(\b(TODO|FIXME|XXX|HACK)\b|待完善|待实现|未实现|暂未实现|暂不支持|后续实现|功能开发中|敬请期待)',
         '逐个核对：已经做完的删掉标记；没做完的对照需求记为功能问题。', code_only=False),
    Rule('FUNC-NOT-IMPLEMENTED', D_FUNC, '中', '方法还是空壳（直接抛「未实现」）', CODE,
         r'(throw\s+new\s+(UnsupportedOperationException|NotImplementedException|NotImplementedError)\(|raise\s+NotImplementedError|throw\s+new\s+Error\(\s*[\'"](not implemented|todo|未实现))',
         '对照需求确认这里是不是应该实现的功能。', skip_if=r'abstract'),
    Rule('FUNC-MOCK-DATA', D_FUNC, '低', '正式代码里有模拟数据或写死的返回', CODE,
         r'\b(const|let|var|private|public|static|final)?\s*(mock|fake|MOCK|FAKE)[A-Z_]\w*\s*(=|:\s*[\[{])',
         '确认是不是该接真实接口或数据库的地方被写死了。',
         skip_if=r'(import|require\(|@Mock|jest\.|vi\.|sinon|unittest\.mock|mockito)'),

    # ---------------- 合理性 / 运维 ----------------
    Rule('OPS-HARDCODED-IP', D_REASON, '低', '写死了服务器地址，换环境要改代码', CODE,
         r'\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b|255\.|localhost)(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b',
         '地址放进配置或环境变量，各环境分开设。',
         skip_if=r'(?i)(version|xmlns|w3\.org|schema|copyright|\bv\d|\d+\.\d+\.\d+\.\d+\.\d+|sha|integrity|ua-parser|user-?agent|mozilla|chrome/|ip\s*[:=]\s*["\']0|如|例如|示例|e\.g\.|placeholder|example)', code_only=True),
    Rule('REASON-SELECT-STAR', D_REASON, '低', 'SQL 用了 select *（字段变动易出错、多查数据）', CODE | {'.xml'},
         r'(?i)["\'`>]\s*select\s+\*\s+from\b', '列出要用的字段。'),
    Rule('REASON-PRINT-STACK', D_REASON, '低', '用 printStackTrace / System.out 打日志', JAVA,
         r'(\.printStackTrace\(\)|System\.(out|err)\.print)', '统一用日志框架，便于线上查问题。'),
    Rule('OPS-DOCKER-LATEST', D_OPS, '低', '镜像版本写 latest 或没写，每次构建可能不一样', {'dockerfile'},
         r'(?i)^\s*FROM\s+(\S+:latest\b|[^:\s@]+\s*$|[^:\s@]+\s+(as|AS)\s+\w+\s*$)',
         '写死具体版本号，升级时再改。', code_only=False,
         skip_if=r'(?i)FROM\s+(scratch|\$\{?\w+\}?)\b'),
    Rule('OPS-CHMOD-777', D_OPS, '中', '把文件权限放到 777（所有人可写）', SH | {'dockerfile'},
         r'chmod\s+(-R\s+)?0?777\b', '按需给最小权限（如 755 / 644）。', code_only=False),
    Rule('OPS-CURL-SH', D_OPS, '中', '下载脚本直接执行，来源被篡改就中招', SH | {'dockerfile'},
         r'(curl|wget)[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b', '先下载、校验后再执行，或用系统包管理器装。', code_only=False),
    Rule('OPS-RM-RF-VAR', D_OPS, '中', '删除命令用了变量，变量为空时会误删', SH,
         r'rm\s+-[rRf]{2}\s+["\']?(\$\{?\w+\}?/?\*?["\']?\s*$|\$\{?\w+\}?/)',
         '先判断变量非空（${VAR:?}），或写死目录。', code_only=False),
    Rule('OPS-SQL-DROP', D_OPS, '中', '数据库脚本里有删表或清表语句', SQL,
         r'(?i)^\s*(drop\s+(table|database|schema)\b(?!\s+if\s+exists)|truncate\s+(table\s+)?\w)',
         '确认这个脚本只用于全新安装；升级脚本不能删数据；部署手册写清楚哪个脚本什么时候跑。',
         escalate=r'(?i)drop\s+(database|schema)', code_only=False),
]

RULES_BY_ID = {r.id: r for r in RULES}

# 弱随机数只在跟安全相关的行上算
_SEC_WORDS = re.compile(r'(?i)(token|captcha|verify|otp|password|pwd|secret|nonce|salt|session|sms|验证码|口令|密码|code\s*=|key\s*=)')
RULES_BY_ID['SEC-WEAK-RANDOM'].filter = lambda m: bool(_SEC_WORDS.search(m.string))

_SENSITIVE = re.compile(r'(?i)(password|passwd|pwd|token|secret|id_?card|bank_?card|card_?no|phone|mobile|身份证|手机号|银行卡)')


def _code_part(line):
    """去掉字符串里的普通文字，只留插值部分（{x}、${x}），看敏感字段是不是作为变量被打印。"""
    def keep(m):
        return ' '.join(re.findall(r'\$?\{[^}]*\}', m.group(0))) or ' "" '
    return re.sub(r'(["\'`])(?:\\.|(?!\1).)*\1', keep, line)


def _logs_sensitive(m):
    line = m.string
    head = line[m.start():]
    return bool(_SENSITIVE.search(_code_part(head).split('(', 1)[-1]))


RULES_BY_ID['SEC-LOG-SENSITIVE'].filter = _logs_sensitive
# 只拼了常量（全大写）的不算
RULES_BY_ID['SEC-SQL-CONCAT'].filter = lambda m: not re.match(r'[A-Z][A-Z0-9_]*\b(?!\s*[(.])', m.string[m.end() - 1:])

COMMENT_LINE = re.compile(r'^\s*(//|#(?!\s*include)|\*|/\*|<!--|--\s|;|rem\s|REM\s|\'\'\'|""")')

SECRET_FILE = re.compile(r'(^|/)(\.env(\.(local|prod|production|dev|development|test|staging))?|id_rsa|id_dsa|id_ecdsa|id_ed25519|[^/]+\.(pem|key|p12|pfx|jks|keystore|ppk|kdbx))$', re.I)
SECRET_FILE_OK = re.compile(r'(example|sample|template|dist|public|\.pub$|test|fixture|mock)', re.I)


def mask(text):
    """把命中行里像口令、密钥的值打码，报告里不出现真实值。"""
    def keep(v):
        if len(v) <= 4:
            return '****'
        return v[:2] + '****' + v[-1:]
    text = re.sub(r'(://[^:/\s"\'@]+:)([^@/\s"\']+)(@)', lambda m: m.group(1) + '****' + m.group(3), text)
    text = re.sub(r'((?:password|pwd)=)([^&\s"\';]+)', lambda m: m.group(1) + '****', text, flags=re.I)
    text = re.sub(r'([:=：>]\s*["\']?)([^\s"\'<,;)]{4,})', lambda m: m.group(1) + keep(m.group(2)), text)
    text = re.sub(r'\b(AKIA|LTAI|AKID)[0-9A-Za-z]{8,}', lambda m: m.group(1) + '****', text)
    return text


# 第三方库、打包好的静态资源：不查写法问题（密钥照查）
VENDOR_PATH = re.compile(r'(^|/)(vendors?|third[_-]?party|3rdparty|static/(js|lib|libs|plugins?)|public/(js|lib|libs|static|plugins?)|resources/static/(js|lib|libs|plugins?)|ueditor|tinymce|ckeditor|pdfjs|monaco|ace-builds|druid/js)/', re.I)
