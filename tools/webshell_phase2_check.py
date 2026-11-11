"""Phase 2 UI check: home page, task page, pet-head reminders and auto-postpone.

Runs the real MainWindow against the built bundle, drives the React UI through
DOM clicks and the reminder cards through their Qt buttons, and asserts both the
rendered text and the sqlite state. Screenshots land in build/.

Usage: python tools/webshell_phase2_check.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6 import QtWebEngineWidgets  # noqa: F401  must be imported before QApplication
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

BUILD = ROOT / 'build'

READY_JS = """(function(){
  var text = document.body.textContent || '';
  return JSON.stringify({
    ready: !!document.querySelector('aside') && text.indexOf('今天安排') !== -1,
    text: text.slice(0, 120),
  });
})()"""

HOME_PROBE_JS = """(function(){
  var text = document.body.textContent || '';
  return JSON.stringify({
    hero: text.indexOf('下一件') !== -1 || text.indexOf('今天没有待办') !== -1,
    stats: ['今天安排', '本周按时打卡', '下一次提醒'].every(function(k){ return text.indexOf(k) !== -1 }),
    rhythm: text.indexOf('今天安排') !== -1,
    log: text.indexOf('小满今天替你做了什么') !== -1,
    nav: document.querySelectorAll('aside nav button').length,
  });
})()"""

SHELL_PROBE_JS = """(function(){
  var shell = document.querySelector('.shell');
  var rail = document.querySelector('.sidebar');
  var button = document.querySelector('aside button[aria-label="收起侧栏"], aside button[aria-label="展开侧栏"]');
  return JSON.stringify({
    collapsed: !!shell && shell.classList.contains('rail-collapsed'),
    width: rail ? Math.round(rail.getBoundingClientRect().width) : -1,
    label: button ? button.getAttribute('aria-label') : '',
  });
})()"""

TASKS_PROBE_JS = """(function(){
  var text = document.body.textContent || '';
  var dt = document.querySelector('input[type="datetime-local"]');
  return JSON.stringify({
    page: !!document.querySelector('input[placeholder="搜索待办标题"]'),
    heading: (document.querySelector('main h1') || {}).textContent || '',
    hasWeekly: text.indexOf('日报') !== -1,
    form: !!document.querySelector('input[placeholder="要做的事"]'),
    dueValue: dt ? dt.value : '',
    hint: text.indexOf('已解析为') !== -1,
  });
})()"""

CLICK_NAV_JS = """(function(label){
  var button = Array.from(document.querySelectorAll('aside button'))
    .find(function(b){ return b.textContent.indexOf(label) !== -1 });
  if (!button) return 'missing';
  button.click();
  return 'ok';
})"""


class Checker:
    def __init__(self, app, window):
        self.app = app
        self.window = window
        self.page = window.web_shell.view.page()
        self.console = []
        self.checks = []
        self.page.javaScriptConsoleMessage = (
            lambda level, message, line, source: self.console.append(f'[{level}] {message} ({source}:{line})'))

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
            return {}

    def click(self, script):
        return self.js(script)

    def reminder_view(self):
        popups = list(self.window.reminder_popups.values())
        popup = popups[0] if popups else None
        text = ' '.join(label.text() for label in popup.findChildren(QLabel)) if popup else ''
        buttons = [button.text().strip() for button in popup.findChildren(QPushButton)] if popup else []
        pet = self.window.pet.frameGeometry()
        rect = popup.frameGeometry() if popup else None
        above = bool(rect) and rect.bottom() <= pet.top() + 84 + 1 \
            and rect.left() <= pet.center().x() <= rect.right()
        return {'present': bool(popup), 'count': len(popups), 'text': text,
                'buttons': buttons, 'above_pet': above, 'popup': repr(rect), 'pet': repr(pet)}

    def click_reminder(self, label):
        popups = list(self.window.reminder_popups.values())
        if not popups:
            return 'missing'
        for button in popups[0].findChildren(QPushButton):
            if button.text().strip() == label:
                button.click()
                return 'ok'
        return 'missing'

    def close_reminder(self):
        popups = list(self.window.reminder_popups.values())
        if not popups:
            return 'missing'
        close = popups[0].findChild(QToolButton, 'reminderClose')
        if close is None:
            return 'missing'
        close.click()
        return 'ok'

    def click_reminder_link(self, label):
        popups = list(self.window.reminder_popups.values())
        if not popups:
            return 'missing'
        for button in popups[0].findChildren(QToolButton):
            if button.text().strip() == label:
                button.click()
                return 'ok'
        return 'missing'

    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:300]})
        if os.environ.get('PHASE2_DEBUG'):
            print(f'CHECK {name}: {ok} {str(detail)[:120]}', flush=True)

    # -- flow ---------------------------------------------------------------

    def wait_ready(self, timeout=25):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.probe(READY_JS).get('ready'):
                return True
            self.sleep(200)
        return False

    def run(self):
        if not self.wait_ready():
            self.check('React 页面就绪', False, self.probe(READY_JS))
            return
        self.check('React 页面就绪', True)
        self.sleep(600)
        home = self.probe(HOME_PROBE_JS)
        self.check('首页 hero/统计/记录渲染', home.get('hero') and home.get('stats') and home.get('rhythm')
                   and home.get('log'), home)
        self.check('侧边栏 4 个入口', home.get('nav') == 4, home.get('nav'))
        rail = self.probe(SHELL_PROBE_JS)
        self.check('侧栏有手动折叠按钮', rail.get('label') in ('收起侧栏', '展开侧栏'), rail)
        self.js("""(function(){
          var button = document.querySelector('aside button[aria-label="收起侧栏"], aside button[aria-label="展开侧栏"]');
          if (button) button.click();
        })()""")
        self.sleep(400)
        toggled = self.probe(SHELL_PROBE_JS)
        self.check('侧栏可手动收起/展开',
                   toggled.get('collapsed') != rail.get('collapsed')
                   and toggled.get('width') == (68 if toggled.get('collapsed') else 232), toggled)
        self.js("""(function(){
          var button = document.querySelector('aside button[aria-label="收起侧栏"], aside button[aria-label="展开侧栏"]');
          if (button) button.click();
        })()""")
        self.sleep(400)
        self.check('侧栏状态可还原', self.probe(SHELL_PROBE_JS).get('collapsed') == rail.get('collapsed'))
        BUILD.mkdir(parents=True, exist_ok=True)
        self.window.grab().save(str(BUILD / 'webshell-home-phase2.png'))

        store = self.window.store
        window = self.window
        window.settings.update({'dnd_enabled': False, 'early_nudge': False, 'auto_postpone': False})

        def overdue(title, **kwargs):
            now = datetime.now(timezone.utc)
            return store.add(title, (now - timedelta(minutes=1)).isoformat(), now - timedelta(minutes=2), **kwargs)

        # 1. reminder card above the pet + complete
        tid = overdue('写周报')
        window.check_due()
        self.sleep(700)
        card = self.reminder_view()
        self.check('到期任务在宠物头顶弹出提醒卡',
                   card.get('present') and card.get('above_pet') and '写周报' in card.get('text', ''), card)
        if card.get('present'):
            list(window.reminder_popups.values())[0].grab().save(
                str(BUILD / 'reminder-popup-phase2.png'))
        self.check('提醒卡按钮齐全',
                   card.get('buttons') == ['完成', '10 分钟后', '今天别再说'], card.get('buttons'))
        self.click_reminder('完成')
        self.sleep(700)
        self.check('提醒卡完成写回数据库', not store.pending()
                   and store.db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == 'done')
        self.check('完成后提醒卡消失', not self.reminder_view().get('present'))

        # 2. snooze
        tid = overdue('开短会')
        window.check_due()
        self.sleep(700)
        self.click_reminder('10 分钟后')
        self.sleep(700)
        row = store.db.execute('SELECT due_at,notified_at FROM tasks WHERE id=?', (tid,)).fetchone()
        self.check('顺延 10 分钟', datetime.fromisoformat(row['due_at']) > datetime.now(timezone.utc)
                   and row['notified_at'] is None and tid not in window.web_reminders, dict(row))

        # 3. open the task page from the card
        tid = overdue('打开待办')
        window.check_due()
        self.sleep(700)
        self.click_reminder_link('打开待办 →')
        self.sleep(1200)
        opened = self.probe(TASKS_PROBE_JS)
        self.check('提醒卡打开待办并跳转任务页',
                   opened.get('page') and not self.reminder_view().get('present'), opened)
        store.complete(tid)

        # 4. mute today
        tid = overdue('喝水')
        window.check_due()
        self.sleep(700)
        self.click_reminder('今天别再说')
        self.sleep(700)
        row = store.db.execute('SELECT muted_until FROM tasks WHERE id=?', (tid,)).fetchone()
        self.check('今日免打扰写入 muted_until',
                   row['muted_until'] == datetime.now().astimezone().date().isoformat(), dict(row))

        # 5. closing the card auto-postpones when enabled
        window.settings['auto_postpone'] = True
        tid = overdue('浇花')
        window.check_due()
        self.sleep(700)
        self.close_reminder()
        self.sleep(700)
        row = store.db.execute('SELECT due_at,notified_at FROM tasks WHERE id=?', (tid,)).fetchone()
        self.check('关闭提醒自动顺延', datetime.fromisoformat(row['due_at']) > datetime.now(timezone.utc)
                   and row['notified_at'] is None and tid not in window.web_reminders, dict(row))
        window.settings['auto_postpone'] = False

        # 6. repeat task complete creates the next occurrence
        tid = overdue('日报', repeat='daily')
        window.check_due()
        self.sleep(700)
        self.click_reminder('完成')
        self.sleep(700)
        done = store.db.execute('SELECT next_id FROM tasks WHERE id=?', (tid,)).fetchone()
        pending = [dict(r) for r in store.pending()]
        self.check('重复任务生成下一次', bool(done['next_id'])
                   and any(r['id'] == done['next_id'] and r['repeat_rule'] == 'daily' for r in pending),
                   {'next': done['next_id'], 'pending': len(pending)})

        # 7. quiet hours suppress, then deliver after switching off
        local = datetime.now().astimezone()
        window.settings.update({
            'dnd_enabled': True,
            'dnd_start': (local - timedelta(hours=1)).strftime('%H:%M'),
            'dnd_end': (local + timedelta(hours=1)).strftime('%H:%M'),
        })
        tid = overdue('静默任务')
        window.check_due()
        window.check_due()
        self.sleep(700)
        quiet = store.db.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='quiet'", (tid,)).fetchone()[0]
        self.check('勿扰时段不弹卡片且只记一次', not self.reminder_view().get('present') and quiet == 1, quiet)
        window.settings['dnd_enabled'] = False
        window.check_due()
        self.sleep(700)
        self.check('关闭勿扰后补发提醒', self.reminder_view().get('present'))
        self.click_reminder('完成')
        self.sleep(500)

        # 8. early nudge stays in the pet bubble
        window.settings['early_nudge'] = True
        now = datetime.now(timezone.utc)
        store.add('早点准备', (now + timedelta(minutes=5)).isoformat(), now)
        window.check_due()
        self.sleep(700)
        bubble = window.pet.bubble
        self.check('提前提醒显示在宠物气泡',
                   '还有' in bubble.text() and '早点准备' in bubble.text() and bubble.isVisible(),
                   bubble.text())
        bubble.hide()
        window.settings['early_nudge'] = False

        # 9. tasks page: list, editor, quick parse, save, history tab
        self.click(CLICK_NAV_JS + '("待办")')
        self.sleep(800)
        tasks = self.probe(TASKS_PROBE_JS)
        self.check('任务页渲染待办与搜索', tasks.get('page') and tasks.get('hasWeekly'), tasks)
        self.window.grab().save(str(BUILD / 'webshell-tasks-phase2.png'))

        self.click("""(function(){
          var button = Array.from(document.querySelectorAll('button'))
            .find(function(b){ return b.textContent.indexOf('新增待办') !== -1 });
          if (!button) return 'missing';
          button.click(); return 'ok';
        })()""")
        self.sleep(500)
        self.check('打开新建表单', self.probe(TASKS_PROBE_JS).get('form'))
        self.js("""(function(){
          function fill(el, value){
            var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
            el.dispatchEvent(new Event('input', { bubbles: true }));
          }
          var title = document.querySelector('input[placeholder="要做的事"]');
          var quick = Array.from(document.querySelectorAll('input'))
            .find(function(i){ return (i.placeholder || '').indexOf('试试') !== -1 });
          if (!title || !quick) return 'missing';
          fill(title, '明天跑步');
          fill(quick, '明天 7:00 跑步');
          return 'ok';
        })()""")
        self.sleep(1200)
        parsed = self.probe(TASKS_PROBE_JS)
        self.check('快速描述解析回显', parsed.get('hint') and 'T07:00' in parsed.get('dueValue', ''), parsed)
        self.click("""(function(){
          var button = Array.from(document.querySelectorAll('button'))
            .find(function(b){ return b.textContent.trim() === '保存' });
          if (!button) return 'missing';
          button.click(); return 'ok';
        })()""")
        self.sleep(900)
        saved = [dict(r) for r in store.pending() if r['title'] == '明天跑步']
        self.check('表单保存新待办', len(saved) == 1
                   and datetime.fromisoformat(saved[0]['due_at']).astimezone().hour == 7, saved[:1])

        self.click("""(function(){
          var button = Array.from(document.querySelectorAll('button'))
            .find(function(b){ return b.textContent.indexOf('已完成') !== -1 });
          if (!button) return 'missing';
          button.click(); return 'ok';
        })()""")
        self.sleep(600)
        self.check('已完成列表可见历史任务', '写周报' in (self.js(
            "document.body.textContent") or ''))

    # -- teardown -----------------------------------------------------------

    def finish(self, error=None):
        probe_console = self.console
        if error:
            self.check('脚本执行', False, error)
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print('RESULT ' + json.dumps(
            {'checks': self.checks, 'console': probe_console, 'screenshots': sorted(
                str(p) for p in BUILD.glob('webshell-*-phase2.png'))},
            ensure_ascii=False, indent=2), flush=True)
        return 0 if all(c['ok'] for c in self.checks) else 1


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if os.environ.get('PHASE2_DEBUG'):
        import faulthandler
        faulthandler.dump_traceback_later(45, repeat=True)
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
