import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, onTasksChanged, Task, TaskEvent, TodayStats } from '../api'
import {
  formatClock, formatDue, isOverdue, isToday, REPEAT_LABELS,
} from '../tasks'
import { Button, Icon, IconName, Paw, Pill } from '../ui'

export default function HomePage(props: {
  onOpenChat: () => void
  onNewTask: () => void
}) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [history, setHistory] = useState<Task[]>([])
  const [stats, setStats] = useState<TodayStats | null>(null)
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const [list, done, today, log] = await Promise.all([
        api.tasksList(), api.tasksHistory('done', ''), api.taskStats(), api.taskTodayEvents(),
      ])
      setTasks(list)
      setHistory(done)
      setStats(today)
      setEvents(log)
      setNotice('')
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '读取待办失败')
    }
  }, [])

  useEffect(() => {
    void load()
    return onTasksChanged(() => void load())
  }, [load])

  const act = async (label: string, run: () => Promise<unknown>) => {
    try {
      await run()
      setNotice('')
      await load()
    } catch (err) {
      setNotice(`${label}失败：${err instanceof Error ? err.message : '请重试'}`)
    }
  }

  const overdue = tasks.filter(isOverdue)
  const todayPending = tasks.filter(isToday)
  const focus = overdue[0] ?? tasks[0]
  const focusOverdue = focus ? isOverdue(focus) : false
  const next = tasks[0]

  const doneToday = useMemo(() => history.filter((task) => task.completed_at && isTodayAt(task.completed_at)), [history])
  const done = stats?.completed_today ?? doneToday.length
  const total = todayPending.length + doneToday.length
  const streakDays = Math.min(7, stats?.week_on_time_days ?? 0)

  const timeline = useMemo(() => {
    const rows: { task: Task; done: boolean }[] = [
      ...todayPending.map((task) => ({ task, done: false })),
      ...doneToday.map((task) => ({ task, done: true })),
    ]
    return rows.sort((a, b) => new Date(a.task.due_at).getTime() - new Date(b.task.due_at).getTime()).slice(0, 6)
  }, [todayPending, doneToday])

  const logCards = useMemo(() => buildLogCards(events), [events])
  const now = new Date()
  const greeting = now.getHours() < 6 ? '夜深了' : now.getHours() < 12 ? '上午好' : now.getHours() < 18 ? '下午好' : '晚上好'
  const dateLine = `${now.getFullYear()} 年 ${now.getMonth() + 1} 月 ${now.getDate()} 日 · 周${'日一二三四五六'[now.getDay()]} · ${formatClock(now.toISOString())}`

  return (
    <div className="page home">
      <header className="page-head">
        <div className="page-head-main">
          <div className="eyebrow">{dateLine}</div>
          <h1 className="home-title">{greeting}</h1>
        </div>
        <div className="home-actions">
          <Button onClick={props.onOpenChat}><Icon name="chat" size={15} />继续对话</Button>
          <Button onClick={props.onOpenChat}><Icon name="calendar" size={15} />今日规划</Button>
          <Button primary onClick={props.onNewTask}><Icon name="plus" size={15} />新增待办</Button>
        </div>
      </header>

      {notice && <p className="status-line alert">{notice}</p>}

      <section className="hero-grid">
        {focus ? (
          <article className={`card hero ${focusOverdue ? 'is-alert' : 'is-calm'}`}>
            <div className="hero-top">
              <span className="hero-ico"><Icon name={focusOverdue ? 'bell' : 'clock'} size={18} /></span>
              <div>
                <p className="hero-kicker">
                  {focusOverdue
                    ? focus.remind_count
                      ? `${formatDue(focus.due_at)} 的提醒，你没有回应`
                      : `${formatDue(focus.due_at)} 的提醒还没有处理`
                    : `下一次提醒在 ${formatDue(focus.due_at)}`}
                </p>
                <p className="hero-sub">
                  {focusOverdue
                    ? focus.remind_count
                      ? `小满在桌面弹过 ${focus.remind_count} 次气泡${focus.dingtalk ? '，也推了钉钉' : ''}，还没有收到你的确认。`
                      : '这件事已过了原定时间，还在等你处理。'
                    : focus.early_notified_at
                      ? '小满会提前 10 分钟提醒你。'
                      : '小满会到点提醒你。'}
                </p>
              </div>
              {focusOverdue ? (
                focus.deferred === 1 ? (
                  <Pill tone="caution"><Icon name="clock" size={12} />已延期</Pill>
                ) : (
                  <Pill tone="danger"><Icon name="alert" size={12} />{overdueText(focus.due_at)}</Pill>
                )
              ) : (
                <Pill tone="plain"><Icon name="clock" size={12} />{formatDue(focus.due_at)}</Pill>
              )}
            </div>
            <h2 className="hero-title">{focus.title}</h2>
            <div className="hero-meta">
              <p className="hero-note">
                {heroCaption(focus, focusOverdue
                  ? (focus.deferred === 1 ? '已延期' : focus.remind_count ? `已提醒 ${focus.remind_count} 次` : '待处理')
                  : '待提醒')}
              </p>
              <div className="hero-due">
                {focusOverdue ? '原定时间' : '下一次提醒'}
                <b>{formatDue(focus.due_at)}</b>
                <span className="hero-due-note">
                  {focusOverdue
                    ? (focus.deferred === 1 ? '提醒已达上限' : '等待你的回应')
                    : `还有 ${countdown(focus.due_at)}`}
                </span>
              </div>
            </div>
            <div className="hero-bar"><span style={{ width: focusOverdue ? '100%' : `${focusProgress(focus)}%` }} /></div>
            <div className="hero-actions">
              {focus.deferred !== 1 && (
                <Button onClick={() => void act('顺延', () => api.taskSnooze(focus.id, 10))}>
                  <Icon name="clock" size={14} />十分钟后
                </Button>
              )}
              <Button onClick={() => void act('完成', () => api.taskComplete(focus.id))}>
                <Icon name="check" size={14} />标记完成
              </Button>
              <Button ghost onClick={() => void act('免打扰', () => api.taskMuteToday(focus.id))}>
                <Icon name="moon" size={14} />今天别再说
              </Button>
              <span className="hint">处理结果会记入今天的工作日志。</span>
            </div>
          </article>
        ) : (
          <article className="card hero is-calm hero-empty">
            <div className="hero-top">
              <span className="hero-ico"><Icon name="sparkles" size={18} /></span>
              <div>
                <p className="hero-kicker">今天没有待办</p>
                <p className="hero-sub">小满在替你看着时间，下一件事到点会主动叫你。</p>
              </div>
            </div>
            <div className="hero-actions">
              <Button primary onClick={props.onNewTask}><Icon name="plus" size={14} />去安排一件事</Button>
              <Button onClick={props.onOpenChat}><Icon name="chat" size={14} />继续对话</Button>
            </div>
          </article>
        )}

        <article className="card card-pad progress-card">
          <div className="progress-top">
            <Ring done={done} total={total} />
            <div>
              <div className="progress-title">今天 {total} 件事</div>
              <p className="progress-sub">
                {total === 0
                  ? '还没有安排，享受一下空档。'
                  : `已完成 ${done} 件，还剩 ${Math.max(0, total - done)} 件待处理。`}
              </p>
            </div>
          </div>
          <div className="streak">
            <Paw size={13} />
            本周按时打卡 {streakDays} 天
            <span className="streak-dots" aria-hidden>
              {Array.from({ length: 7 }, (_, index) => (
                <span key={index} className={`streak-dot${index < streakDays ? ' on' : ''}`} />
              ))}
            </span>
          </div>
          <div className="progress-track" aria-hidden>
            <span style={{ width: `${total > 0 ? Math.round((done / total) * 100) : 0}%` }} />
          </div>
          <div className="next-row">
            <div className="next-main">
              <div className="next-label">下一次提醒</div>
              <div className="next-time">{next ? formatDue(next.due_at) : '暂无'}</div>
              {next && <div className="next-title">{next.title}</div>}
            </div>
            {Boolean(next?.dingtalk) && <Pill tone="calm"><Icon name="send" size={11} />钉钉</Pill>}
          </div>
        </article>
      </section>

      <div className="home-cols">
        <section>
          <div className="section-head">
            <span className="section-title">今天安排</span>
            <span className="section-meta">{todayPending.length + doneToday.length} 项</span>
          </div>
          {timeline.length === 0 ? (
            <div className="card empty-card">
              <span className="empty-icon calm"><Paw size={17} /></span>
              <p className="empty-title">今天没有要盯的事了</p>
              <p className="empty-desc">新增一件待办，或让对话助手替你记下。</p>
            </div>
          ) : (
            <div className="day-list">
              {timeline.map(({ task, done: isDone }) => (
                <DayRow key={task.id} task={task} done={isDone} />
              ))}
            </div>
          )}
        </section>

        <section>
          <div className="section-head">
            <span className="section-title">小满今天替你做了什么</span>
          </div>
          {logCards.length === 0 ? (
            <div className="log-empty">
              <span className="log-card-ico calm"><Paw size={15} /></span>
              <p className="log-empty-text">
                今天还没有需要记录的动静。新增待办或和对话助手聊聊，小满会把动作记在这里。
              </p>
            </div>
          ) : (
            <div className="log-grid">
              {logCards.map((card) => (
                <div key={card.title} className="log-card">
                  <span className={`log-card-ico ${card.tone}`}><Icon name={card.icon} size={15} /></span>
                  <div>
                    <div className="log-card-title">{card.title}</div>
                    <p className="log-card-desc">{card.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function DayRow(props: { task: Task; done: boolean }) {
  const { task, done } = props
  const overdue = !done && isOverdue(task)
  const late = done && task.completed_at
    ? Math.round((new Date(task.completed_at).getTime() - new Date(task.due_at).getTime()) / 60000)
    : 0
  const sub = done
    ? `${formatClock(task.completed_at ?? task.due_at)} 完成${late > 0 ? `，晚 ${late} 分钟` : '，很准时'}`
    : task.note || (task.dingtalk ? '钉钉' : '')
  return (
    <div className={`day-row${done ? ' done' : overdue ? ' overdue' : ''}`}>
      <div className="day-time">{formatClock(task.due_at)}</div>
      <span className={`day-dot${done ? ' done' : overdue ? ' overdue' : ''}`} aria-hidden>
        {done && <Icon name="check" size={10} />}
      </span>
      <div className="day-main">
        <div className="day-title">{task.title}</div>
        {sub && <div className="day-sub">{sub}</div>}
      </div>
      <div className="day-side">
        {done ? (
          <Pill tone="calm"><Icon name="check" size={11} />已完成</Pill>
        ) : (
          <Pill tone={overdue ? 'danger' : 'plain'}>
            {overdue
              ? <><Icon name="alert" size={11} />{overdueText(task.due_at)}</>
              : <><Icon name="clock" size={11} />{formatDue(task.due_at)}</>}
          </Pill>
        )}
      </div>
    </div>
  )
}

function Ring(props: { done: number; total: number }) {
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const ratio = props.total > 0 ? Math.min(1, props.done / props.total) : 0
  return (
    <svg className="progress-ring" viewBox="0 0 64 64" role="img" aria-label={`今日进度 ${props.done}/${props.total}`}>
      <circle cx="32" cy="32" r={radius} fill="none" stroke="var(--surface-3)" strokeWidth="5" />
      {ratio > 0 && (
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke="var(--calm)"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={`${circumference * ratio} ${circumference}`}
          transform="rotate(-90 32 32)"
        />
      )}
      <text x="32" y="36.5" textAnchor="middle" fontSize="13" fontWeight="700" fill="var(--ink)">
        {props.done}/{props.total}
      </text>
    </svg>
  )
}

function overdueText(iso: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000))
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours) return `逾期 ${hours}小时${rest}分`
  if (minutes) return `逾期 ${minutes}分`
  return '逾期 刚刚'
}

function countdown(iso: string): string {
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
  if (seconds <= 0) return '现在'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${Math.max(1, minutes)}分钟`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时`
  const days = Math.floor(hours / 24)
  return hours % 24 ? `${days}天${hours % 24}时` : `${days}天`
}

function heroCaption(task: Task, state: string): string {
  const parts = [state]
  if (task.repeat_rule !== 'none') parts.push(REPEAT_LABELS[task.repeat_rule])
  if (Boolean(task.dingtalk)) parts.push('钉钉同步')
  return parts.join(' · ')
}

type LogCardData = { title: string; desc: string; icon: IconName; tone: 'brand' | 'caution' | 'calm' }

function buildLogCards(events: TaskEvent[]): LogCardData[] {
  const counts: Record<string, number> = {}
  for (const event of events) counts[event.kind] = (counts[event.kind] ?? 0) + 1
  const created = events.filter((event) => event.kind === 'created'
    && (event.detail === 'chat' || event.detail === 'draft')).length
  const completed = counts.completed ?? 0
  const postponed = (counts.snoozed ?? 0) + (counts.auto_postponed ?? 0)
  const reminded = counts.reminded ?? 0
  const quiet = counts.quiet ?? 0
  const early = counts.early ?? 0
  const cards: LogCardData[] = []
  if (created) {
    cards.push({
      title: `听懂并记下 ${created} 件事`,
      desc: '从对话里补上时间，才建的任务。',
      icon: 'chat',
      tone: 'brand',
    })
  }
  if (reminded || quiet) {
    let title = `提醒 ${reminded} 次`
    if (quiet) title += ` · 免打扰 ${quiet} 次`
    let desc = '桌面气泡与提前提点按待办标记执行。'
    if (early) desc += ` 其中 ${early} 次是提前提点。`
    cards.push({ title, desc, icon: 'bell', tone: 'caution' })
  }
  if (completed || postponed) {
    cards.push({
      title: `结掉 ${completed} 件、顺延 ${postponed} 件`,
      desc: '完成时刻已记入今天的工作日志。',
      icon: 'tasks',
      tone: 'calm',
    })
  }
  return cards
}

function focusProgress(task: Task): number {
  const due = new Date(task.due_at).getTime()
  const now = Date.now()
  if (due <= now) return 100
  const hours = Math.min(6, (due - now) / 3600000)
  return Math.max(12, Math.round(100 - (hours / 6) * 88))
}

function isTodayAt(iso: string): boolean {
  const date = new Date(iso)
  const now = new Date()
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
}
