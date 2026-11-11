"""Phase 3 UI check: chat sessions, streaming, stop, regenerate, task receipts, drafts and planning.

Runs the real MainWindow against the built bundle. The model pipeline is
replaced by a scripted QObject factory so no network or API key is needed;
everything else (bridge, TaskStore, React UI) is the production path.

Usage: python tools/webshell_phase3_check.py
Run without QT_QPA_PLATFORM=offscreen when you need build screenshots; offscreen
WebEngine content is not captured by QWidget.grab().
"""
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6 import QtWebEngineWidgets  # noqa: F401  must be imported before QApplication
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

BUILD = ROOT / 'build'

INIT_READY_JS = """(function(){
  var text = document.body.textContent || '';
  return JSON.stringify({
    ready: document.querySelectorAll('aside button').length >= 4
      && text.indexOf('小满') !== -1,
  });
})()"""

CHAT_READY_JS = """(function(){
  var text = document.body.textContent || '';
  var area = document.querySelector('textarea');
  return JSON.stringify({
    rail: text.indexOf('当前对话') !== -1,
    empty: text.indexOf('和小满聊聊今天要做什么') !== -1,
    composer: !!area,
    nav: document.querySelectorAll('aside nav button').length,
  });
})()"""

CHAT_PROBE_JS = """(function(){
  var text = document.body.textContent || '';
  var area = document.querySelector('textarea');
  return JSON.stringify({
    text: text,
    input: area ? area.value : '',
    buttons: Array.from(document.querySelectorAll('button')).map(function(b){ return b.textContent.trim() }),
    drafts: text.indexOf('待办草稿') !== -1,
    stream: text.indexOf('正在回复…') !== -1 || text.indexOf('正在搜索资料…') !== -1
      || text.indexOf('正在查本地资料…') !== -1,
    stopped: text.indexOf('已停止，未保存这条回复') !== -1,
    heading: (document.querySelector('main h1') || {}).textContent || '',
  });
})()"""

CHAT_LAYOUT_JS = """(function(){
  var content = document.querySelector('main.content');
  var page = document.querySelector('.chat-page');
  var stream = document.querySelector('.chat-stream');
  var cr = content ? content.getBoundingClientRect() : null;
  var pr = page ? page.getBoundingClientRect() : null;
  var doc = document.scrollingElement;
  return JSON.stringify({
    chatClass: !!content && content.classList.contains('content-chat'),
    overflow: content ? getComputedStyle(content).overflowY : '',
    scrollbarWidth: content ? getComputedStyle(content).scrollbarWidth : '',
    fits: !!(cr && pr && pr.bottom <= cr.bottom + 1 && pr.top >= cr.top - 1),
    pageScroll: doc ? doc.scrollHeight - doc.clientHeight : -1,
    streamOverflow: stream ? getComputedStyle(stream).overflowY : '',
  });
})()"""

CLICK_NAV_JS = """(function(label){
  var button = Array.from(document.querySelectorAll('aside nav button'))
    .find(function(b){ return b.textContent.indexOf(label) !== -1 });
  if (!button) return 'missing';
  try { button.click(); } catch (e) { return 'throw:' + (e && (e.message || e)); }
  return 'ok';
})"""

FILL_JS = """(function(value){
  var el = document.querySelector('textarea');
  if (!el) return 'missing';
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return 'ok';
})"""

CLICK_TEXT_JS = """(function(label){
  var button = Array.from(document.querySelectorAll('button'))
    .find(function(b){ return b.textContent.trim() === label });
  if (!button) return 'missing';
  try { button.click(); } catch (e) { return 'throw:' + (e && (e.message || e)); }
  return 'ok';
})"""

CLICK_ARIA_JS = """(function(label){
  var button = Array.from(document.querySelectorAll('button'))
    .find(function(b){ return (b.getAttribute('aria-label') || b.title || '') === label });
  if (!button) return 'missing';
  try { button.click(); } catch (e) { return 'throw:' + (e && (e.message || e)); }
  return 'ok';
})"""

SELECT_SESSION_JS = """(function(label){
  var sel = document.querySelector('select.chat-session-select');
  if (!sel) return 'missing';
  var opt = Array.from(sel.options).find(function(o){ return o.textContent.trim() === label });
  if (!opt) return 'missing-option';
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, opt.value);
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  return 'ok';
})"""


class FakeWorker(QObject):
    """Scripted stand-in for AssistantWorker; emits the real signal contract."""

    result = Signal(str)
    failed = Signal(str)
    chunk = Signal(str)
    stopped = Signal()
    search_started = Signal()
    searched = Signal(object)
    search_failed = Signal(str)
    knowledge_started = Signal()
    knowledge_searched = Signal(object)
    finished = Signal()

    def __init__(self, settings, messages, tasks, parent=None, web_query='',
                 knowledge=None, knowledge_query=''):
        super().__init__(parent)
        self.messages = messages
        self.tasks = tasks
        self.web_query = web_query
        self.knowledge_query = knowledge_query
        self.cancel_event = threading.Event()
        self.blocks = 0
        self.timers = []
        self.text = next((m.get('content', '') for m in reversed(messages)
                          if m.get('role') == 'user'), '')

    # -- plumbing -----------------------------------------------------------

    def _after(self, ms, fn):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(fn)
        timer.start(ms)
        self.timers.append(timer)

    def _stop_timers(self):
        for timer in self.timers:
            timer.stop()

    def cancel(self):
        self.cancel_event.set()
        self._stop_timers()
        if self.blocks:
            self.blocks = -1
            self._after(10, self._cancel_tail)

    def start(self):
        self.blocks = 1
        if self.knowledge_query:
            self.blocks += 1
        if self.text.startswith('请根据下面的只读待办快照'):
            self._after(30, self._plan)
        elif '慢慢' in self.text:
            self._after(30, self._slow_start)
        elif '天气' in self.text:
            self._after(30, self._weather)
        elif '买咖啡' in self.text:
            self._after(30, self._ambiguous)
        elif '开会' in self.text:
            self._after(30, self._task_create)
        else:
            self._after(40, lambda: self._finish('这是重新生成的另一个版本。'))

    # -- behaviours ---------------------------------------------------------

    def _cancel_tail(self):
        self.stopped.emit()
        self.finished.emit()

    def _finish(self, content, delay=40):
        if self.cancel_event.is_set():
            return
        self.result.emit(content)
        self._after(delay, self.finished.emit)

    def _slow_start(self):
        if self.cancel_event.is_set():
            return
        self._after(20, lambda: self._slow_chunk(0))

    def _slow_chunk(self, index):
        if self.cancel_event.is_set():
            return
        pieces = ['好，', '我先', '把节奏', '放慢，', '一件一件', '来整理。']
        if index >= len(pieces):
            self._finish('好，我先把节奏放慢，一件一件来整理。')
            return
        self.chunk.emit(pieces[index])
        self._after(500, lambda: self._slow_chunk(index + 1))

    def _weather(self):
        if self.cancel_event.is_set():
            return
        self.knowledge_started.emit()
        self.knowledge_searched.emit([{
            'doc_id': 'doc-1', 'doc_name': '出行约定', 'title': '出行约定',
            'kind': 'wiki', 'text': '早晚温差大，带外套。'}])
        self.search_started.emit()
        self.searched.emit([{
            'title': '天气来源示例', 'url': 'https://example.com/weather',
            'content': '今日多云转晴', 'published_date': '2026-11-10'}])
        pieces = ['今天', '多云转晴', '，气温 12–20℃', '。']
        for offset, piece in enumerate(pieces):
            self._after(120 * (offset + 5), lambda text=piece: (
                None if self.cancel_event.is_set() else self.chunk.emit(text)))
        self._after(120 * (len(pieces) + 5), lambda: self._finish(
            '\n\n'.join(['今天多云转晴，气温 12–20℃。',
                         '- 出门带件外套\n- 晚间有风',
                         '[天气来源示例](https://example.com/weather)'])))

    def _task_create(self):
        if self.cancel_event.is_set():
            return
        due = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0)
        content = ('好的，已经记下了。\n\n```tasks\n'
                   + json.dumps([{'title': '开会', 'due_at': due.isoformat(),
                                  'repeat': 'none'}], ensure_ascii=False)
                   + '\n```')
        self._finish(content)

    def _ambiguous(self):
        rows = [row for row in self.tasks if row.get('title') == '买咖啡']
        content = ('找到两条同名待办，请确认。\n\n```tasks\n'
                   + json.dumps([{'action': 'complete', 'id': rows[0]['id']}],
                                ensure_ascii=False)
                   + '\n```')
        self._finish(content)

    def _plan(self):
        if self.cancel_event.is_set():
            return
        self.chunk.emit('先看逾期的，再排稍后的。')
        self._finish('\n\n'.join(['今天建议先完成逾期任务，再处理稍后的安排。',
                                  '1. 先做最重要的\n2. 留出缓冲时间']))


class Checker:
    def __init__(self, app, window):
        self.app = app
        self.window = window
        self.page = window.web_shell.view.page()
        self.console = []
        self.checks = []
        self.page.javaScriptConsoleMessage = (
            lambda level, message, line, source: self.console.append(
                f'[{level}] {message} ({source}:{line})'))

    # -- primitives ---------------------------------------------------------

    def js(self, script, timeout=5000):
        loop = QEventLoop()
        box = {}

        def done(result):
            box['value'] = result
            loop.quit()

        self.page.runJavaScript(script, done)
        QTimer.singleShot(timeout, loop.quit)
        loop.exec()
        return box.get('value')

    def sleep(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def probe(self, script):
        raw = self.js(script)
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            if os.environ.get('PHASE3_DEBUG'):
                print(f'PROBE_BAD raw={str(raw)[:200]!r}', flush=True)
            return {}

    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]})
        if os.environ.get('PHASE3_DEBUG'):
            print(f'CHECK {name}: {ok} {str(detail)[:160]}', flush=True)

    def wait_for(self, predicate, timeout=8, step=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            self.sleep(step)
        return None

    def send(self, text, wait=1200):
        # The composer swaps 发送 for 停止 while a reply is in flight.
        ready = self.wait_for(lambda: '发送' in self.probe(CHAT_PROBE_JS).get('buttons', []),
                              timeout=6, step=100)
        if not ready:
            self.check(f'发送前等待空闲（{text}）', False,
                       self.probe(CHAT_PROBE_JS).get('buttons', []))
            return
        self.js(f"""({FILL_JS})({json.dumps(text, ensure_ascii=False)})""")
        self.sleep(200)
        clicked = self.js(CLICK_TEXT_JS + '("发送")')
        if clicked != 'ok':
            self.check(f'发送按钮可点击（{text}）', False, clicked)
        self.sleep(wait)

    # -- flow ---------------------------------------------------------------

    def run(self):
        if not self.wait_for(lambda: self.probe(INIT_READY_JS).get('ready'), timeout=25):
            self.check('React 页面就绪', False, self.probe(INIT_READY_JS))
            return
        clicked = self.js(CLICK_NAV_JS + '("对话")')
        self.sleep(900)
        ready = self.wait_for(lambda: self.probe(CHAT_READY_JS).get('rail'), timeout=8)
        initial = self.probe(CHAT_READY_JS)
        self.check('对话页渲染会话选择与空状态',
                   clicked == 'ok' and ready and initial.get('empty'),
                   {'click': clicked, **initial})
        self.check('侧边栏仍为 4 个入口', initial.get('nav') == 4, initial.get('nav'))
        layout = self.probe(CHAT_LAYOUT_JS)
        self.check('对话页无滚动条且填满内容区',
                   layout.get('chatClass') and layout.get('overflow') == 'hidden'
                   and layout.get('scrollbarWidth') == 'none' and layout.get('fits')
                   and layout.get('pageScroll', 0) <= 1,
                   layout)
        BUILD.mkdir(parents=True, exist_ok=True)
        self.window.grab().save(str(BUILD / 'webshell-chat-phase3.png'))

        store = self.window.store
        window = self.window
        window.settings.update({'dnd_enabled': False, 'early_nudge': False,
                                'auto_postpone': False})
        window.settings['model'] = ''
        window.settings['base_url'] = ''

        # 1. local rules: natural wording becomes a stored task and shows a receipt.
        self.send('明天 09:00 提醒我开会', wait=900)
        page = self.probe(CHAT_PROBE_JS)
        saved = [row for row in store.pending() if row['title'] == '开会']
        self.check('本地规则创建待办并写入数据库', len(saved) == 1, saved[:1])
        self.check('对话渲染任务回执', '已保存：开会' in page.get('text', '')
                   and '已同步到任务页' in page.get('text', ''), page.get('text', '')[-300:])

        # 2. session switch keeps the unsent composer text.
        self.js(CLICK_TEXT_JS + '("新对话")')
        self.sleep(700)
        self.js(f"""({FILL_JS})("还没发出去的内容")""")
        self.sleep(800)
        self.js(SELECT_SESSION_JS + '("默认对话")')
        self.sleep(600)
        self.js(SELECT_SESSION_JS + '("新对话")')
        self.sleep(800)
        self.check('切换会话后恢复未发送输入',
                   self.probe(CHAT_PROBE_JS).get('input') == '还没发出去的内容',
                   self.probe(CHAT_PROBE_JS).get('input'))

        # Back to the default session for the model-driven flows.
        self.js(SELECT_SESSION_JS + '("默认对话")')
        self.sleep(700)
        window.store.save_input('default', '')

        # 3. scripted model: search + knowledge + streaming + final render.
        workers = []

        def factory(*args, **kwargs):
            worker = FakeWorker(*args, **kwargs)
            workers.append(worker)
            return worker

        window.bridge.context['worker_factory'] = factory
        window.settings['model'] = 'fake-model'
        window.settings['base_url'] = 'https://example.invalid'
        window.web_search_ready = lambda: True
        window.knowledge_ready = lambda: True
        # Reload the page so the chat session picks up hasModel=true.
        self.js(CLICK_NAV_JS + '("首页")')
        self.sleep(400)
        self.js(CLICK_NAV_JS + '("对话")')
        self.sleep(800)

        self.send('查一下今天的天气', wait=800)
        streaming = self.probe(CHAT_PROBE_JS)
        self.check('流式输出中途可见', '今天' in streaming.get('text', '')
                   and streaming.get('stream'), streaming.get('text', '')[-200:])
        self.window.grab().save(str(BUILD / 'webshell-chat-streaming-phase3.png'))
        final = self.wait_for(lambda: ('联网来源' in self.probe(CHAT_PROBE_JS).get('text', '')
                                       and '本地资料' in self.probe(CHAT_PROBE_JS).get('text', '')), timeout=6)
        page = self.probe(CHAT_PROBE_JS)
        self.check('搜索结果与本地命中渲染为来源',
                   bool(final) and '天气来源示例' in page.get('text', '')
                   and '出行约定' in page.get('text', ''), page.get('text', '')[-400:])
        self.check('流式结束后不重复渲染', page.get('text', '').count('今天多云转晴') == 1,
                   page.get('text', '').count('今天多云转晴'))
        self.check('桥把搜索意图透传给模型', workers and workers[-1].web_query == '查一下今天的天气'
                   and workers[-1].knowledge_query == '查一下今天的天气',
                   getattr(workers[-1], 'web_query', None))

        # 4. regenerate branches into a new session after an answered turn.
        ready = self.wait_for(lambda: self.js("""(function(){
          var b = document.querySelector('button[aria-label="重新生成"]');
          return !!b && !b.disabled;
        })()"""), timeout=6, step=100)
        regen_click = self.js(CLICK_ARIA_JS + '("重新生成")')
        branch = '另一版 · 默认对话'
        loaded = self.wait_for(
            lambda: branch in self.probe(CHAT_PROBE_JS).get('text', '')
            and '今天多云转晴' in self.probe(CHAT_PROBE_JS).get('text', ''),
            timeout=6)
        page = self.probe(CHAT_PROBE_JS)
        self.check('重新生成创建分支会话', bool(ready) and bool(loaded),
                   {'click': regen_click, 'text': page.get('text', '')[-300:]})
        self.check('分支会话写回数据库', window.active_session != 'default'
                   and any(row['title'] == branch for row in store.sessions()),
                   window.active_session)

        # Back to the default session so the chat state stays predictable.
        self.js(SELECT_SESSION_JS + '("默认对话")')
        self.sleep(700)

        # 5. stop keeps the partial text out of history and stores retry context.
        self.send('慢慢说', wait=650)
        before = store.message_count('default')
        stopped_click = self.js(CLICK_TEXT_JS + '("停止")')
        self.sleep(900)
        page = self.probe(CHAT_PROBE_JS)
        self.check('停止后显示已停止状态', page.get('stopped'),
                   {'click': stopped_click, 'text': page.get('text', '')[-300:]})
        self.check('停止不写入助手回复', store.message_count('default') == before,
                   store.message_count('default'))
        self.check('停止保存可重试上下文', 'default' in window.retry_by_session,
                   list(window.retry_by_session))

        # 6. ambiguous task op renders numbered choice buttons and applies the pick.
        now = datetime.now().astimezone()
        first = store.add('买咖啡', (now + timedelta(hours=2)).isoformat(), now, source='chat')
        store.add('买咖啡', (now + timedelta(hours=3)).isoformat(), now, source='chat')
        self.send('帮我处理买咖啡', wait=1200)
        page = self.probe(CHAT_PROBE_JS)
        self.check('多义任务渲染序号按钮', '找到 2 条「买咖啡」' in page.get('text', '')
                   and '1' in page.get('buttons', []) and '2' in page.get('buttons', []),
                   page.get('buttons', [])[-10:])
        self.js(CLICK_TEXT_JS + '("1")')
        self.sleep(900)
        status = store.db.execute(
            'SELECT status FROM tasks WHERE id=?', (first,)).fetchone()[0]
        self.check('选择序号后完成对应待办', status == 'done', status)
        self.check('选择后追加完成回执', '已完成：买咖啡' in self.probe(CHAT_PROBE_JS).get('text', ''),
                   self.probe(CHAT_PROBE_JS).get('text', '')[-300:])

        # 7. daily planning preview then snapshot card.
        self.js(CLICK_TEXT_JS + '("今日规划")')
        self.sleep(500)
        preview = self.probe(CHAT_PROBE_JS)
        self.check('规划预览显示只读快照', '今日规划' in preview.get('text', '')
                   and '开始规划' in preview.get('buttons', []), preview.get('buttons', [])[-6:])
        self.js(CLICK_TEXT_JS + '("开始规划")')
        self.sleep(1400)
        page = self.probe(CHAT_PROBE_JS)
        self.check('规划结果渲染快照卡', '今日规划快照' in page.get('text', '')
                   and '先做最重要的' in page.get('text', ''), page.get('text', '')[-500:])
        self.check('规划提问以友好文案显示', '帮我规划今天' in page.get('text', ''),
                   page.get('text', '')[-500:])

        # 8. draft card: confirm creates a task and jumps to the task page.
        due = (now + timedelta(hours=4)).isoformat()
        store.save_draft('整理会议纪要', due, session_id='default', repeat='none',
                         note='草稿备注')
        self.js(CLICK_NAV_JS + '("首页")')
        self.sleep(500)
        self.js(CLICK_NAV_JS + '("对话")')
        self.sleep(900)
        page = self.probe(CHAT_PROBE_JS)
        self.check('草稿卡渲染到对话', page.get('drafts') and '整理会议纪要' in page.get('text', ''),
                   page.get('text', '')[-300:])
        self.window.grab().save(str(BUILD / 'webshell-chat-draft-phase3.png'))
        self.js(CLICK_TEXT_JS + '("直接创建")')
        self.sleep(900)
        page = self.probe(CHAT_PROBE_JS)
        created = [row for row in store.pending() if row['title'] == '整理会议纪要']
        self.check('确认草稿落库', len(created) == 1, created[:1])
        self.check('确认后跳转任务页', page.get('heading') == '待办事项', page.get('heading'))

        self.check('控制台零报错', not [line for line in self.console if '[Error]' in line],
                   self.console[-5:])

    # -- teardown -----------------------------------------------------------

    def finish(self, error=None):
        if error:
            self.check('脚本执行', False, error)
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print('RESULT ' + json.dumps(
            {'checks': self.checks, 'console': self.console, 'screenshots': sorted(
                str(p) for p in BUILD.glob('webshell-*-phase3.png'))},
            ensure_ascii=False, indent=2), flush=True)
        return 0 if all(c['ok'] for c in self.checks) else 1


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if os.environ.get('PHASE3_DEBUG'):
        import faulthandler
        faulthandler.dump_traceback_later(60, repeat=True)
    temp = tempfile.TemporaryDirectory()
    os.environ['DESKTOP_PET_DATA_DIR'] = temp.name
    (Path(temp.name) / 'settings.json').write_text(
        json.dumps({'theme': 'light', 'dnd_enabled': False,
                    'early_nudge': False, 'auto_postpone': False}), encoding='utf-8')
    app = QApplication(sys.argv)
    from desktop_pet.app import MainWindow

    window = MainWindow()
    window.timer.stop()
    window.resize(1180, 840)
    window.show()

    checker = Checker(app, window)
    scope = {'code': 1, 'error': None}

    def drive():
        try:
            checker.run()
        except Exception as exc:  # noqa: BLE001 - report instead of dying mid-loop
            scope['error'] = exc
        finally:
            scope['code'] = checker.finish(scope['error'])
            window.shutting_down = True
            window.pet.close()
            window.tray.hide()
            window.close()

    QTimer.singleShot(0, drive)
    app.exec()
    window.store.close()
    temp.cleanup()
    return scope.get('code', 1)


if __name__ == '__main__':
    sys.exit(main())
