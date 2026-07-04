#!/usr/bin/env python3
"""lark-agent: 飞书私聊自主智能体——飞书生态的对话入口。

耳朵 = lark-cli 无界事件流(常驻子进程+队列,思考时消息排队不丢)
大脑 = LiteLLM 网关(经 ssh 隧道到 dev,OpenAI 兼容 function calling,带重试)
手   = lark-cli 全域命令(日历/文档/多维表格/消息/任务/邮件……)
记忆 = SQLite(重启不失忆,待确认操作也可跨重启)
安全 = 读操作放行;未知/写操作拦下预览 → 飞书里回「确认」→ 执行

依赖:仅 python3 标准库 + 已登录的 lark-cli。
"""
import argparse
import fcntl
import json
import os
import queue
import shlex
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))

CLI_ENV = {
    **os.environ,
    'LARKSUITE_CLI_NO_UPDATE_NOTIFIER': '1',
    'LARKSUITE_CLI_NO_SKILLS_NOTIFIER': '1',
}

# ── 安全闸 ────────────────────────────────────────────────────────────
# 允许的 lark-cli 一级服务;auth/config/event 永不开放给大脑
ALLOWED_SERVICES = {
    'im', 'docs', 'base', 'sheets', 'calendar', 'mail', 'task', 'contact',
    'wiki', 'drive', 'minutes', 'vc', 'okr', 'approval', 'attendance',
    'search', 'api', 'whoami', 'doctor',
}
# 命令部含这些词根 → 写操作;含 READ_HINTS → 读;两边都不沾 → 默认当写(宁可多确认)
WRITE_VERBS = (
    'create', 'update', 'upsert', 'delete', 'remove', 'send', 'reply',
    'forward', 'recall', 'upload', 'import', 'move', 'copy', 'bind',
    'invite', 'add', 'set', 'write', 'batch', 'arrange', 'cancel', 'done',
    'complete', 'reopen', 'insert', 'append', 'submit', 'approve', 'reject',
    'publish', 'merge', 'edit', 'rename', 'archive', 'restore', 'revoke',
    'patch', 'put', 'post', 'transfer', 'apply', 'grant', 'join', 'pin',
)
READ_HINTS = (
    'list', 'get', 'search', 'fetch', 'read', 'agenda', 'freebusy',
    'status', 'query', 'resolve', 'find', 'primary', 'suggestion',
    'download', 'meta', 'history', 'count', 'export',
)
CONFIRM_WORDS = {'确认', '确定', '执行', 'yes', 'y'}
CANCEL_WORDS = {'取消', '算了', '不用', '不要', 'no', 'n'}
PENDING_TTL = 600  # 秒,待确认操作的有效期


def classify(argv):
    """返回 'blocked' | 'write' | 'read'。只看命令部(首个 flag 之前),不看参数值。"""
    if not argv or argv[0] not in ALLOWED_SERVICES:
        return 'blocked'
    if argv[0] in ('whoami', 'doctor'):
        return 'read'
    if argv[0] == 'api':
        method = argv[1].upper() if len(argv) > 1 else ''
        return 'read' if method == 'GET' else 'write'
    cmd = []
    for tok in argv[1:]:
        if tok.startswith('-'):
            break
        cmd.append(tok.lower())
    joined = ' '.join(cmd)
    if not joined:
        return 'read'  # 如 service --help
    if any(v in joined for v in WRITE_VERBS):
        return 'write'
    if any(v in joined for v in READ_HINTS):
        return 'read'
    return 'write'  # 未知命令默认当写,宁可多一次确认


def run_cli(argv, timeout=90):
    p = subprocess.run(['lark-cli'] + argv, capture_output=True, text=True,
                       env=CLI_ENV, timeout=timeout, cwd=HERE)
    out = (p.stdout or '') + (('\n' + p.stderr) if p.stderr.strip() else '')
    return p.returncode, out.strip()


# ── 记忆(SQLite,仅主线程使用)─────────────────────────────────────────
def db_init(path):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS messages('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, role TEXT, content TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS seen(message_id TEXT PRIMARY KEY, ts REAL)')
    con.execute('CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)')
    con.commit()
    return con


def db_remember(con, role, content):
    con.execute('INSERT INTO messages(ts, role, content) VALUES(?,?,?)',
                (time.time(), role, content))
    con.commit()


def db_history(con, n=12):
    rows = con.execute('SELECT role, content FROM messages ORDER BY id DESC LIMIT ?',
                       (n,)).fetchall()
    return [{'role': r, 'content': c} for r, c in reversed(rows)]


def db_seen_check(con, message_id):
    row = con.execute('SELECT 1 FROM seen WHERE message_id=?', (message_id,)).fetchone()
    return row is not None


def db_seen_mark(con, message_id):
    """回复完成后才登记——宁可重投递时重复回,不可崩溃后永久漏答。"""
    con.execute('INSERT OR IGNORE INTO seen(message_id, ts) VALUES(?,?)',
                (message_id, time.time()))
    con.commit()


def db_kv_set(con, k, v):
    if v is None:
        con.execute('DELETE FROM kv WHERE k=?', (k,))
    else:
        con.execute('INSERT OR REPLACE INTO kv(k, v) VALUES(?,?)', (k, json.dumps(v)))
    con.commit()


def db_kv_get(con, k):
    row = con.execute('SELECT v FROM kv WHERE k=?', (k,)).fetchone()
    return json.loads(row[0]) if row else None


# ── 大脑 ──────────────────────────────────────────────────────────────
TOOLS = [{
    'type': 'function',
    'function': {
        'name': 'lark',
        'description': (
            '执行 lark-cli 命令读写 Sean 的飞书(日历/文档/多维表格/消息/任务/邮件等)。'
            '传参数串,不含 lark-cli 前缀。只读命令直接执行;'
            '写命令会被安全闸拦下转 Sean 人工确认,不会直接生效。'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'args': {'type': 'string',
                         'description': "例: calendar +agenda --as user"},
            },
            'required': ['args'],
        },
    },
}]


def llm(base_url, key, model, messages, retries=3):
    payload = {'model': model, 'messages': messages, 'max_tokens': 800,
               'tools': TOOLS}
    req_body = json.dumps(payload).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                base_url.rstrip('/') + '/chat/completions', data=req_body,
                headers={'Authorization': f'Bearer {key}',
                         'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)['choices'][0]['message']
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < retries - 1:
                wait = 2 * (attempt + 1)
                print(f'[llm] 第{attempt + 1}次失败({type(e).__name__}),{wait}s 后重试', flush=True)
                time.sleep(wait)
    raise last


def _load_doc(name):
    """读取同目录下的可选文档(缺失则返回空串)。"""
    path = os.path.join(HERE, name)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ''


def build_system(model):
    cookbook = _load_doc('cookbook.md')
    # 私有资产绑定(open_id / Base·文档 token / 群 chat_id 等)放在 assets.local.md,
    # 已 gitignore、不进公开仓库;缺失时这段自动省略。格式见 assets.example.md。
    assets = _load_doc('assets.local.md')
    return (
        '你是"小爪",Sean 的飞书私聊智能体,常驻运行,'
        f'大脑是他自建 LiteLLM 网关后面的 {model},手是 lark 工具(受控执行 lark-cli)。\n'
        '原则:\n'
        '- 需要事实(日程/文档/表格/消息)时先调工具查,不要凭空编\n'
        '- 默认加 --as user(以 Sean 的身份);发消息等 bot 能干的用 --as bot\n'
        '- 响应信封是 {ok, identity, data},数据在 .data 下;可用 --jq 精简输出\n'
        '- 写操作不要自己先问要不要执行——直接调 lark 工具,安全闸会拦下它、生成预览且绝不会真执行;'
        '拿到 WRITE_BLOCKED 结果后,你再把预览要点转述给 Sean(系统会自动附上待确认命令清单)\n'
        '- 回复简短、直接、带点幽默的中文,两三句为宜;查到的数据用清爽的列表呈现\n'
        + ('\n# 已知资产\n' + assets if assets else '')
        + ('\n# lark-cli 命令速查\n' + cookbook if cookbook else '')
    )


# ── 耳朵:无界监听(常驻子进程 + 队列)──────────────────────────────────
class Ear:
    def __init__(self, q):
        self.q = q
        self.stop = threading.Event()
        self.proc = None
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def _loop(self):
        backoff = 2
        while not self.stop.is_set():
            try:
                # stdin 必须挂着:无界 consume 收到 stdin EOF 会优雅退出
                # errors='replace':stderr 混入非 UTF-8 字节时解码不抛异常
                self.proc = subprocess.Popen(
                    ['lark-cli', 'event', 'consume', 'im.message.receive_v1', '--as', 'bot'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, errors='replace',
                    env=CLI_ENV)
                print(f'[ear] 监听进程启动 pid={self.proc.pid}', flush=True)
                for line in self.proc.stdout:
                    line = line.strip()
                    if 'websocket: connected' in line:
                        print('[ear] WebSocket 已连接', flush=True)
                        backoff = 2
                    if not line.startswith('{'):
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get('type') == 'im.message.receive_v1':
                        self.q.put(d)
            except Exception as e:  # 耳朵线程绝不能死:任何异常都走重启
                print(f'[ear] 异常: {e!r}', flush=True)
            if self.stop.is_set():
                break
            code = self.proc.poll() if self.proc else '?'
            print(f'[ear] 监听进程退出(code={code}),{backoff}s 后重启', flush=True)
            self.stop.wait(backoff)
            backoff = min(backoff * 2, 60)

    def shutdown(self):
        self.stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()  # SIGTERM,避免泄漏服务端订阅
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print('[ear] 监听进程未按时退出', flush=True)


def reply(message_id, text):
    try:
        subprocess.run(
            ['lark-cli', 'im', '+messages-reply', '--as', 'bot',
             '--message-id', message_id, '--text', text],
            capture_output=True, text=True, env=CLI_ENV, timeout=60)
    except subprocess.TimeoutExpired:
        print('[mouth] 回复超时', flush=True)


# ── 工具循环 ──────────────────────────────────────────────────────────
def handle_turn(cfg, history, user_text):
    """跑一轮对话(含最多 6 轮工具调用)。返回 (回复文本, pending or None)。"""
    # 显式取北京时间——这台 Mac 系统时区是美西,不能用本地时间
    now = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M %A')
    msgs = [{'role': 'system',
             'content': cfg['system'] + f'\n当前北京时间: {now}。Sean 在中国,所有日期时间推算以此为准,严禁猜测。'}] \
        + history[-12:] + [{'role': 'user', 'content': user_text}]
    blocked = []  # 本轮被拦下的全部写命令,按序累积
    for _ in range(6):
        m = llm(cfg['base_url'], cfg['key'], cfg['model'], msgs)
        calls = m.get('tool_calls')
        if not calls:
            answer = (m.get('content') or '(空回复)').strip()
            pending = {'items': blocked, 'ts': time.time()} if blocked else None
            return answer, pending
        msgs.append({'role': 'assistant', 'content': m.get('content'),
                     'tool_calls': calls})
        for c in calls:
            try:
                args_str = json.loads(c['function']['arguments'])['args']
                argv = shlex.split(args_str)
            except (json.JSONDecodeError, KeyError, ValueError,
                    TypeError, AttributeError) as e:
                result = f'参数解析失败: {e}'
                argv = None
            if argv is not None:
                kind = classify(argv)
                print(f'[tool] ({kind}) lark-cli {args_str[:120]}', flush=True)
                if kind == 'blocked':
                    result = f'BLOCKED: 服务 {argv[0] if argv else "?"} 不在白名单内'
                elif kind == 'read':
                    try:
                        code, out = run_cli(argv)
                        result = out[:3500] or f'(exit {code},无输出)'
                    except subprocess.TimeoutExpired:
                        result = 'TIMEOUT: 命令超时'
                else:  # write → 拦截,生成预览
                    preview = args_str
                    if '--dry-run' not in argv:
                        try:
                            code, out = run_cli(argv + ['--dry-run'], timeout=30)
                            if code == 0 and out:
                                preview = out[:600]
                        except subprocess.TimeoutExpired:
                            pass
                    blocked.append(args_str)
                    result = ('WRITE_BLOCKED: 写操作需 Sean 确认,尚未执行。'
                              '请向 Sean 概述将做什么(系统会自动附命令清单)。\n'
                              f'命令: lark-cli {args_str}\n预览:\n{preview}')
            msgs.append({'role': 'tool', 'tool_call_id': c['id'],
                         'content': result})
    pending = {'items': blocked, 'ts': time.time()} if blocked else None
    return '(工具调用轮数超限,先歇口气)', pending


def execute_pending(pending):
    """逐条执行已确认的写命令,每条单独报结果。"""
    outs = []
    for args_str in pending['items']:
        argv = [a for a in shlex.split(args_str) if a not in ('--dry-run', '--yes')]
        try:
            code, out = run_cli(argv)
            if code == 10:  # CLI 高危写协议:已获 Sean 确认,带 --yes 重跑
                code, out = run_cli(argv + ['--yes'])
        except subprocess.TimeoutExpired:
            outs.append(f'❌ 超时: {args_str[:80]}')
            continue
        mark = '✅' if code == 0 else f'❌(exit {code})'
        outs.append(f'{mark} lark-cli {args_str[:80]}\n{out[:300]}')
    return '\n\n'.join(outs)


# ── 主循环 ────────────────────────────────────────────────────────────
def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    load_dotenv(os.path.join(HERE, '.env'))
    ap = argparse.ArgumentParser(description='飞书生态对话智能体')
    ap.add_argument('--minutes', type=int, default=int(os.environ.get('LARK_AGENT_MINUTES', 0)),
                    help='运行窗口(分钟),0=常驻')
    ap.add_argument('--max-msgs', type=int, default=int(os.environ.get('LARK_AGENT_MAX_MSGS', 0)),
                    help='最多处理条数,0=不限')
    ap.add_argument('--only-sender', default=os.environ.get('LARK_AGENT_ONLY_SENDER', ''),
                    help='只回复该 open_id(留空=不过滤)')
    args = ap.parse_args()

    # 单实例锁:双实例会导致每条消息被回两遍(事件总线向所有消费者分发)
    lockf = open(os.path.join(HERE, '.agent.lock'), 'w')
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('另一个小爪实例已在运行,拒绝双开(锁: .agent.lock)')
    lockf.write(str(os.getpid()))
    lockf.flush()

    key = os.environ.get('LITELLM_API_KEY')
    if not key:
        raise SystemExit('缺 LITELLM_API_KEY(放 .env;别忘了先开 ssh 隧道)')
    cfg = {
        'key': key,
        'base_url': os.environ.get('LITELLM_BASE_URL', 'http://127.0.0.1:14000/v1'),
        'model': os.environ.get('LARK_AGENT_MODEL', 'deepseek/deepseek-chat'),
    }
    cfg['system'] = build_system(cfg['model'])

    con = db_init(os.path.join(HERE, 'memory.db'))
    history = db_history(con)
    pending = db_kv_get(con, 'pending')

    q = queue.Queue()
    ear = Ear(q)

    def _on_term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _on_term)
    ear.start()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    handled = 0
    last_hb = time.time()
    print(f"[agent] 小爪上线 v3(model={cfg['model']},窗口={args.minutes or '∞'}min,"
          f"记忆={len(history)}条,待确认={'有' if pending else '无'})", flush=True)
    try:
        while True:
            if args.max_msgs and handled >= args.max_msgs:
                break
            if deadline and time.time() >= deadline:
                break
            if time.time() - last_hb > 3600:
                print(f'[hb] alive,已处理 {handled} 条,耳朵{"存活" if ear.thread.is_alive() else "已死"}',
                      flush=True)
                last_hb = time.time()
            try:
                ev = q.get(timeout=30)
            except queue.Empty:
                continue
            if args.only_sender and ev.get('sender_id') != args.only_sender:
                print(f'[agent] 忽略非白名单发送者 {ev.get("sender_id")}', flush=True)
                continue
            mid = ev.get('message_id')
            if not mid:
                print('[agent] 事件缺 message_id,跳过(无法回复)', flush=True)
                continue
            if db_seen_check(con, mid):
                print('[agent] 跳过重投递', flush=True)
                continue
            text = ev.get('content', '').strip()
            print(f'[agent] 收到: {text[:100]}', flush=True)
            t0 = time.time()

            stripped = text.strip('!!。.~ ').lower()
            try:
                if pending and stripped in CONFIRM_WORDS:
                    todo, pending = pending, None
                    # 先清持久化再执行:崩溃时宁可漏执行(可重说),不可重复执行
                    db_kv_set(con, 'pending', None)
                    if time.time() - todo.get('ts', 0) > PENDING_TTL:
                        answer = '这个待确认操作放了太久已作废,需要的话重新说一遍。'
                    else:
                        answer = execute_pending(todo)
                    db_remember(con, 'user', text)
                    db_remember(con, 'assistant', answer)
                    history += [{'role': 'user', 'content': text},
                                {'role': 'assistant', 'content': answer}]
                elif pending and stripped in CANCEL_WORDS:
                    pending = None
                    db_kv_set(con, 'pending', None)
                    answer = '好,已取消,啥也没动。'
                    db_remember(con, 'user', text)
                    db_remember(con, 'assistant', answer)
                    history += [{'role': 'user', 'content': text},
                                {'role': 'assistant', 'content': answer}]
                else:
                    if pending:
                        pending = None  # 岔开话题视为放弃待确认操作
                        db_kv_set(con, 'pending', None)
                    answer, pending = handle_turn(cfg, history, text)
                    if pending:
                        cmds = '\n'.join(f'{i}. lark-cli {a}'
                                         for i, a in enumerate(pending['items'], 1))
                        answer += ('\n\n⏸ 待确认命令(仅回「确认」二字执行全部,回「取消」放弃):\n'
                                   + cmds)
                    db_kv_set(con, 'pending', pending)
                    db_remember(con, 'user', text)
                    db_remember(con, 'assistant', answer)
                    history += [{'role': 'user', 'content': text},
                                {'role': 'assistant', 'content': answer}]
                    history = history[-12:]
            except Exception as e:  # 单条消息失败不拖垮主循环,且留痕免失忆
                answer = f'(这条我处理挂了: {type(e).__name__},再试一次?)'
                print(f'[agent] 处理异常: {e!r}', flush=True)
                db_remember(con, 'user', text)
                db_remember(con, 'assistant', answer)
                history += [{'role': 'user', 'content': text},
                            {'role': 'assistant', 'content': answer}]
            reply(mid, answer)
            db_seen_mark(con, mid)  # 回复后才登记:宁可重投递重复回,不可漏答
            print(f'[agent] 已回({time.time() - t0:.1f}s): {answer[:120]}', flush=True)
            handled += 1
    except KeyboardInterrupt:
        print('\n[agent] 收到退出信号', flush=True)
    finally:
        ear.shutdown()
    print(f'[agent] 下线:共处理 {handled} 条', flush=True)


if __name__ == '__main__':
    main()
