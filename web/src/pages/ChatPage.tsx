import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, AssistantResult, AssistantState, ChatMessage, ChatPlanPreview, ChatSession,
  ChatSessionPayload, ChatSnapshot, Draft, KnowledgeHit, PlanResult, SearchSource, Task,
  onAssistantChunk, onAssistantFailed, onAssistantResult, onAssistantState,
  onChatChanged, onPlanResult, onTasksChanged,
} from '../api'
import { Button, Icon, Paw, Pill } from '../ui'
import { formatClock, formatDue, isToday, REPEAT_LABELS } from '../tasks'
import Markdown from '../components/Markdown'

type UiMessage = ChatMessage & {
  sources?: SearchSource[]
  knowledge?: KnowledgeHit[]
  meta?: string
  tasks?: string[]
  choice?: string | null
}

type Stream = { jobId: string | null; text: string }

const BUSY_STATES = new Set(['responding', 'searching', 'knowledge'])

const STATE_LABEL: Record<string, string> = {
  idle: '可发送新消息',
  responding: '正在回复…',
  searching: '正在搜索资料…',
  knowledge: '正在查本地资料…',
  stopped: '已停止，未保存这条回复',
  failed: '回复失败，可重试',
}

function choiceCount(prompt: string): number {
  return (prompt.match(/(^|\n)\s*\d+\.\s/g) ?? []).length
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const area = document.createElement('textarea')
  area.value = text
  document.body.appendChild(area)
  area.select()
  document.execCommand('copy')
  area.remove()
}

function formatSnapshotTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString('zh-CN', {
      month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
}

export default function ChatPage(props: {
  onOpenTasks: () => void
  onOpenSettings: () => void
}) {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [sideTasks, setSideTasks] = useState<Task[]>([])
  const [active, setActive] = useState('')
  const [payload, setPayload] = useState<ChatSessionPayload | null>(null)
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [input, setInput] = useState('')
  const [state, setState] = useState<AssistantState>({ state: 'idle' })
  const [streams, setStreams] = useState<Record<string, Stream>>({})
  const [liveSources, setLiveSources] = useState<SearchSource[]>([])
  const [liveKnowledge, setLiveKnowledge] = useState<KnowledgeHit[]>([])
  const [failure, setFailure] = useState<{ sessionId: string; message: string } | null>(null)
  const [notice, setNotice] = useState('')
  const [sending, setSending] = useState(false)
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null)
  const [planPreview, setPlanPreview] = useState<ChatPlanPreview | null>(null)
  const [planCard, setPlanCard] = useState<PlanResult | null>(null)

  const activeRef = useRef('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  const loadSession = useCallback(async (sessionId?: string) => {
    const data = await api.chatSession(sessionId)
    activeRef.current = data.session.id
    setActive(data.session.id)
    setPayload(data)
    setMessages(data.messages.map((message) => ({ ...message })))
    setDrafts(data.drafts)
    setInput(data.session.inputText)
    setFailure(null)
    setPlanCard(null)
    setEditing(null)
    stickRef.current = true
    if (data.busy && data.busySessionId) {
      setState((prev) => (prev.state === 'idle'
        ? { state: 'responding', sessionId: data.busySessionId }
        : prev))
    }
  }, [])

  const refreshSessions = useCallback(async () => {
    try {
      const data = await api.chatSessions()
      setSessions(data.sessions)
    } catch {
      // Session list refresh is best-effort; the next event retries.
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await api.chatSessions()
        if (cancelled) return
        setSessions(data.sessions)
        await loadSession(data.activeSession)
      } catch (err) {
        if (!cancelled) setNotice(err instanceof Error ? err.message : '读取对话失败')
      }
    })()
    return () => { cancelled = true }
  }, [loadSession])

  useEffect(() => {
    const load = () => {
      void api.tasksList()
        .then((rows) => setSideTasks(rows))
        .catch(() => {})
    }
    load()
    return onTasksChanged(load)
  }, [])

  useEffect(() => onAssistantState((update) => {
    setState(update)
    if (update.sources) setLiveSources(update.sources)
    if (update.knowledge) setLiveKnowledge(update.knowledge)
    if (update.state === 'idle' || update.state === 'stopped' || update.state === 'failed') {
      if (update.sessionId) {
        setStreams((prev) => {
          if (!(update.sessionId! in prev)) return prev
          const next = { ...prev }
          delete next[update.sessionId!]
          return next
        })
      }
      setLiveSources([])
      setLiveKnowledge([])
    }
  }), [])

  useEffect(() => onAssistantChunk((update) => {
    const sessionId = update.sessionId || activeRef.current
    setStreams((prev) => {
      const current = prev[sessionId] ?? { jobId: update.jobId ?? null, text: '' }
      if (update.jobId && current.jobId && update.jobId !== current.jobId) return prev
      return {
        ...prev,
        [sessionId]: { jobId: update.jobId ?? current.jobId, text: current.text + update.text },
      }
    })
  }), [])

  const appendResult = useCallback((result: AssistantResult) => {
    const message: UiMessage = {
      role: 'assistant',
      content: result.reply,
      sources: result.sources,
      knowledge: result.knowledge,
      meta: result.meta,
      tasks: result.tasks,
      choice: result.choice,
    }
    setMessages((prev) => {
      const next = [...prev, message]
      if (result.note) next.push({ role: 'system', content: result.note })
      result.notices.forEach((text) => next.push({ role: 'system', content: text }))
      return next
    })
  }, [])

  useEffect(() => onAssistantResult((result) => {
    setStreams((prev) => {
      if (!(result.sessionId in prev)) return prev
      const next = { ...prev }
      delete next[result.sessionId]
      return next
    })
    setLiveSources([])
    setLiveKnowledge([])
    setFailure((prev) => (prev?.sessionId === result.sessionId ? null : prev))
    if (result.sessionId === activeRef.current) appendResult(result)
    void refreshSessions()
  }), [appendResult, refreshSessions])

  useEffect(() => onAssistantFailed((update) => {
    const sessionId = update.sessionId || activeRef.current
    setStreams((prev) => {
      if (!(sessionId in prev)) return prev
      const next = { ...prev }
      delete next[sessionId]
      return next
    })
    setFailure({ sessionId, message: update.message })
  }), [])

  useEffect(() => onPlanResult((result) => setPlanCard(result)), [])
  useEffect(() => onChatChanged(() => void refreshSessions()), [refreshSessions])

  // Persist the unsent composer text so a page reload or session switch keeps it.
  useEffect(() => {
    if (!active) return
    const timer = window.setTimeout(() => {
      void api.chatSaveInput(active, input).catch(() => {})
    }, 400)
    return () => window.clearTimeout(timer)
  }, [input, active])

  const stream = streams[active]
  const streamText = stream?.text ?? ''
  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages, streamText, planCard, drafts, active])

  const busy = BUSY_STATES.has(state.state)
  const otherBusy = busy && !!state.sessionId && state.sessionId !== active
  const title = sessions.find((row) => row.id === active)?.title
    ?? payload?.session.title ?? '对话'
  const canRegenerate = !!payload?.hasModel
    && !busy
    && messages.some((message) => message.role === 'assistant')
  const failureVisible = failure?.sessionId === active
  const activePlan = planCard && planCard.sessionId === active ? planCard : null
  const railToday = sideTasks.filter(isToday)
  const modelLabel = payload?.hasModel ? '模型聊天' : '本地规则'

  const onScroll = () => {
    const el = scrollRef.current
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const act = async (label: string, run: () => Promise<unknown>) => {
    setNotice('')
    try {
      await run()
    } catch (err) {
      setNotice(`${label}失败：${err instanceof Error ? err.message : '请重试'}`)
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || busy || sending) return
    setSending(true)
    setNotice('')
    setFailure(null)
    stickRef.current = true
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    try {
      await api.chatSend(activeRef.current, text)
    } catch (err) {
      setMessages((prev) => prev.slice(0, -1))
      setInput(text)
      setNotice(err instanceof Error ? err.message : '发送失败')
    } finally {
      setSending(false)
    }
  }

  const stop = () => void act('停止', () => api.chatStop())
  const retry = () => failure && void act('重试', async () => {
    await api.chatRetry(failure.sessionId)
    setFailure(null)
  })

  const regenerate = () => void act('重新生成', async () => {
    const result = await api.chatRegenerate(activeRef.current)
    await refreshSessions()
    await loadSession(result.sessionId)
  })

  const createSession = () => void act('新建对话', async () => {
    const data = await api.chatCreateSession()
    await refreshSessions()
    await loadSession(data.sessionId)
  })

  const commitRename = async () => {
    if (!editing) return
    const nextTitle = editing.title.trim()
    if (!nextTitle) {
      setEditing(null)
      return
    }
    try {
      await api.chatRenameSession(editing.id, nextTitle)
      setEditing(null)
      await refreshSessions()
    } catch (err) {
      setNotice(`重命名失败：${err instanceof Error ? err.message : '请重试'}`)
    }
  }

  const choose = (index: number) => void act('选择待办', async () => {
    await api.chatChooseTask(activeRef.current, index)
    await refreshSessions()
  })

  const confirmDraft = (draft: Draft) => void act('创建待办', async () => {
    await api.draftConfirm(draft.id)
    setDrafts((prev) => prev.filter((row) => row.id !== draft.id))
    props.onOpenTasks()
  })

  const discardDraft = (draft: Draft) => void act('丢弃草稿', async () => {
    await api.draftDiscard(draft.id)
    setDrafts((prev) => prev.filter((row) => row.id !== draft.id))
  })

  const previewPlan = () => void act('读取今日清单', async () => {
    setPlanPreview(await api.chatPlanPreview(activeRef.current))
  })

  const startPlan = async () => {
    setPlanPreview(null)
    stickRef.current = true
    setMessages((prev) => [...prev, { role: 'user', content: '帮我规划今天' }])
    try {
      await api.chatPlanStart(activeRef.current)
    } catch (err) {
      setMessages((prev) => prev.slice(0, -1))
      setNotice(err instanceof Error ? err.message : '规划失败')
    }
  }

  const status = busy && otherBusy
    ? '其他对话正在回复，可继续浏览和编辑'
    : state.state === 'idle' && !payload?.hasModel
      ? '本地规则模式'
      : STATE_LABEL[state.state] ?? ''

  return (
    <div className="chat-page">
      <div className="chat">
        <section className="chat-main">
          <header className="chat-head">
            <span className="chat-head-label">当前对话</span>
            {editing ? (
              <input
                className="field chat-session-select"
                autoFocus
                value={editing.title}
                maxLength={60}
                onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                onBlur={() => void commitRename()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void commitRename()
                  if (e.key === 'Escape') setEditing(null)
                }}
              />
            ) : (
              <select
                className="field chat-session-select"
                value={active}
                aria-label="切换对话"
                onChange={(e) => {
                  const next = e.target.value
                  if (next !== active) void act('切换对话', () => loadSession(next))
                }}
              >
                {!sessions.some((row) => row.id === active) && <option value={active}>{title}</option>}
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>{session.title}</option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="icon-btn"
              title="重命名当前对话"
              aria-label="重命名当前对话"
              onClick={() => setEditing({ id: active, title })}
            >
              <Icon name="edit" size={14} />
            </button>
            <button
              type="button"
              className="icon-btn"
              title="复制对话内容"
              aria-label="复制对话内容"
              onClick={() => void act('复制对话', async () => {
                const text = messages
                  .map((message) => message.role === 'user'
                    ? `我：${message.content}`
                    : message.role === 'assistant' ? `小满：${message.content}` : message.content)
                  .join('\n\n')
                await copyText(text || '（空对话）')
              })}
            >
              <Icon name="copy" size={14} />
            </button>
            <span className="spacer" />
            <Button small onClick={previewPlan} disabled={busy}>
              <Icon name="sparkles" size={14} />今日规划
            </Button>
            <Button small primary onClick={createSession}>
              <Icon name="plus" size={14} />新对话
            </Button>
          </header>

          <div ref={scrollRef} onScroll={onScroll} className="chat-stream">
            {messages.length === 0 && !streamText && drafts.length === 0 && (
              <div className="chat-empty">
                <span className="rail-logo"><Paw size={22} /></span>
                <p className="chat-empty-title">和小满聊聊今天要做什么</p>
                <p className="chat-empty-text">
                  可以直接说「明天 9 点提醒我开会」，也可以让它帮你整理和修改待办。
                </p>
              </div>
            )}
            {messages.map((message, index) => (
              <MessageRow
                key={`${index}-${message.role}`}
                message={message}
                onOpenTasks={props.onOpenTasks}
                onChoose={choose}
                busy={busy}
              />
            ))}
            {drafts.map((draft) => (
              <DraftPanel
                key={draft.id}
                draft={draft}
                onConfirm={() => confirmDraft(draft)}
                onDiscard={() => discardDraft(draft)}
              />
            ))}
            {(streamText || (busy && state.sessionId === active)) && (
              <StreamRow
                text={streamText}
                status={status}
                sources={liveSources}
                knowledge={liveKnowledge}
              />
            )}
            {failureVisible && (
              <div className="failure">
                <p>{failure.message}</p>
                <div className="failure-actions">
                  <Button small primary onClick={retry}>重试这条</Button>
                  <Button small onClick={() => setFailure(null)}>先放着</Button>
                </div>
              </div>
            )}
            {activePlan && <PlanSnapshotCard plan={activePlan} />}
          </div>

          <footer className="composer">
            <textarea
              rows={2}
              value={input}
              maxLength={12000}
              placeholder={otherBusy ? '其他对话正在回复，可先浏览' : '说出事项和时间，小满替你记成待办'}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void send()
                }
              }}
            />
            <div className="composer-foot">
              <Pill>{payload?.hasModel ? '模型聊天' : '本地规则'}</Pill>
              <span className={`composer-status${notice ? ' status-line alert' : ''}`}>
                {notice || status}
              </span>
              {payload?.retryable && !busy && <span className="msg-meta">上次请求可以重试</span>}
              {payload?.choicePending && <span className="msg-meta">回复序号处理多义待办</span>}
              <span className="spacer" />
              <span className="msg-meta">Ctrl+Enter 发送</span>
              <button
                type="button"
                className="icon-btn"
                title="重新生成上一条回复"
                aria-label="重新生成"
                disabled={!canRegenerate}
                onClick={regenerate}
              >
                <Icon name="refresh" size={15} />
              </button>
              {busy ? (
                <Button small danger onClick={stop}><Icon name="stop" size={13} />停止</Button>
              ) : (
                <Button small primary disabled={!input.trim() || sending} onClick={() => void send()}>
                  <Icon name="send" size={13} />发送
                </Button>
              )}
            </div>
          </footer>
        </section>

        <aside className="chat-rail" aria-label="对话侧栏">
          <section className="rail-sec">
            <div className="rail-sec-title">
              <Icon name={drafts.length ? 'edit' : 'tasks'} size={13} />
              {drafts.length ? '待确认的草稿' : '还没有落成待办'}
            </div>
            <p className="rail-sec-note">
              {drafts.length
                ? `有 ${drafts.length} 条草稿等你确认，确认后才会写入待办。`
                : '说清事项和时间，小满会先给出草稿，确认后才写入待办。'}
            </p>
          </section>

          <section className="rail-sec">
            <dl className="rail-kv">
              <dt>对话</dt><dd>{title}</dd>
              <dt>消息</dt><dd>{messages.length} 条</dd>
              <dt>模型</dt><dd>{modelLabel}</dd>
            </dl>
          </section>

          <section className="rail-sec">
            <div className="rail-sec-title">今天安排 · {railToday.length} 项</div>
            {railToday.length === 0 ? (
              <p className="rail-mini-empty">今天没有安排。</p>
            ) : (
              <div className="rail-mini-list">
                {railToday.slice(0, 4).map((task) => (
                  <div key={task.id} className="rail-mini-row">
                    <time>{formatClock(task.due_at)}</time>
                    <span>{task.title}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="rail-actions">
            <button type="button" className="rail-action" onClick={previewPlan}>
              <Icon name="calendar" size={13} />今日规划
            </button>
            <button type="button" className="rail-action" onClick={props.onOpenTasks}>
              <Icon name="tasks" size={13} />打开待办
            </button>
            <button type="button" className="rail-action" onClick={props.onOpenSettings}>
              <Icon name="settings" size={13} />改提醒设置
            </button>
          </div>

          <p className="rail-foot">桌面气泡加声音；只有标记「钉钉通知」的事才会推群。</p>
        </aside>
      </div>

      {planPreview && (
        <PlanPreviewDialog
          preview={planPreview}
          onCancel={() => setPlanPreview(null)}
          onConfirm={() => void startPlan()}
        />
      )}
    </div>
  )
}

function MessageRow(props: {
  message: UiMessage
  onOpenTasks: () => void
  onChoose: (index: number) => void
  busy: boolean
}) {
  const { message } = props
  if (message.role === 'system') {
    return (
      <div className="msg-note">
        <span><Icon name="check" size={11} />{message.content}</span>
      </div>
    )
  }
  if (message.role === 'user') {
    return (
      <div className="msg user">
        <div className="bubble-user">{message.content}</div>
        <span className="msg-user-avatar"><Icon name="user" size={13} /></span>
      </div>
    )
  }
  const choices = message.choice ? choiceCount(message.choice) : 0
  return (
    <div className="msg">
      <span className="msg-avatar"><Paw size={14} /></span>
      <div className="bubble">
        <Markdown text={message.content} />
        {message.choice && choices > 0 && (
          <div className="choice-box">
            <p>{message.choice}</p>
            <div className="choice-btns">
              {Array.from({ length: choices }, (_, i) => i + 1).map((index) => (
                <button
                  key={index}
                  type="button"
                  disabled={props.busy}
                  className="choice-btn"
                  onClick={() => props.onChoose(index)}
                >
                  {index}
                </button>
              ))}
            </div>
          </div>
        )}
        <Materials sources={message.sources} knowledge={message.knowledge} />
        <div className="msg-foot">
          {message.tasks && message.tasks.length > 0 && (
            <button type="button" className="msg-link" onClick={props.onOpenTasks}>
              已同步到任务页 →
            </button>
          )}
          {message.meta && <span className="msg-meta">{message.meta}</span>}
        </div>
      </div>
    </div>
  )
}

function StreamRow(props: {
  text: string
  status: string
  sources: SearchSource[]
  knowledge: KnowledgeHit[]
}) {
  return (
    <div className="msg">
      <span className="msg-avatar"><Paw size={14} /></span>
      <div className="bubble streaming">
        {props.text
          ? <Markdown text={props.text} />
          : <p className="status-line">{props.status || '正在思考…'}</p>}
        <Materials sources={props.sources} knowledge={props.knowledge} />
        {props.text && <p className="msg-meta" style={{ marginTop: 5 }}>{props.status}</p>}
      </div>
    </div>
  )
}

function Materials(props: { sources?: SearchSource[]; knowledge?: KnowledgeHit[] }) {
  const sources = props.sources ?? []
  const knowledge = props.knowledge ?? []
  if (sources.length === 0 && knowledge.length === 0) return null
  return (
    <div className="materials">
      {knowledge.length > 0 && (
        <div>
          <span className="materials-label">本地资料</span>
          <div className="material-chips">
            {knowledge.slice(0, 4).map((hit, index) => (
              <Pill key={index}>
                {hit.doc_name || hit.title || '资料'}
                {hit.kind === 'wiki' ? ' · Wiki' : ' · 原文'}
              </Pill>
            ))}
          </div>
        </div>
      )}
      {sources.length > 0 && (
        <div>
          <span className="materials-label">联网来源</span>
          {sources.slice(0, 4).map((source, index) => (
            <a
              key={`${source.url}-${index}`}
              className="material-link"
              href={source.url}
              target="_blank"
              rel="noreferrer"
              title={source.title}
              style={{ display: 'block' }}
            >
              {index + 1}. {source.title}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function DraftPanel(props: { draft: Draft; onConfirm: () => void; onDiscard: () => void }) {
  const { draft } = props
  return (
    <div className="draft">
      <div className="draft-head">
        <Pill tone="brand">待办草稿</Pill>
        <span className="msg-meta">{formatDue(draft.due_at)} · {REPEAT_LABELS[draft.repeat_rule]}</span>
      </div>
      <p className="draft-title">{draft.title}</p>
      {draft.note && <p className="draft-note">{draft.note}</p>}
      <div className="draft-actions">
        <Button small primary onClick={props.onConfirm}>直接创建</Button>
        <Button small onClick={props.onDiscard}>先放着</Button>
      </div>
    </div>
  )
}

function PlanPreviewDialog(props: {
  preview: ChatPlanPreview
  onCancel: () => void
  onConfirm: () => void
}) {
  const { snapshot } = props.preview
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="今日规划预览">
      <div className="modal">
        <div className="modal-head">
          <Icon name="calendar" size={16} />
          <h3 className="modal-title">今日规划</h3>
          <Pill tone="brand">{props.preview.usesModel ? '会调用模型' : '本地整理'}</Pill>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
          <SnapshotCounts snapshot={snapshot} />
          <SnapshotList snapshot={snapshot} />
          <p className="modal-note">只读快照，不会修改待办；规划结果里的任务仍需你确认。</p>
          <div className="modal-foot">
            <Button small onClick={props.onCancel}>取消</Button>
            <Button small primary onClick={props.onConfirm}>开始规划</Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function PlanSnapshotCard(props: { plan: PlanResult }) {
  return (
    <div className="card card-pad" style={{ width: '100%', maxWidth: 820, margin: '0 auto' }}>
      <div className="draft-head">
        <Pill tone="brand">今日规划快照</Pill>
        <span className="msg-meta">{formatSnapshotTime(props.plan.snapshot.at)}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 9 }}>
        <SnapshotCounts snapshot={props.plan.snapshot} />
        <SnapshotList snapshot={props.plan.snapshot} />
      </div>
    </div>
  )
}

function SnapshotCounts(props: { snapshot: ChatSnapshot }) {
  const { snapshot } = props
  return (
    <div className="count-grid">
      <div className="count-tile">
        <b>{snapshot.overdue_count}</b>
        <span>逾期</span>
      </div>
      <div className="count-tile">
        <b>{snapshot.today_count}</b>
        <span>今天稍后</span>
      </div>
      <div className="count-tile">
        <b>{snapshot.future_count}</b>
        <span>未来日期</span>
      </div>
    </div>
  )
}

function SnapshotList(props: { snapshot: ChatSnapshot }) {
  const { snapshot } = props
  return (
    <div className="snapshot-list">
      {snapshot.overdue.length > 0 && (
        <div>
          <p className="snapshot-group-label alert">逾期</p>
          {snapshot.overdue.map((item, index) => (
            <p key={`o-${index}`} className="snapshot-row">
              <span className="when">{formatDue(item.due_at)}</span>
              <span className="sep">·</span>{item.title}
              <span className="repeat">（{item.repeat}）</span>
            </p>
          ))}
        </div>
      )}
      {snapshot.today.length > 0 && (
        <div>
          <p className="snapshot-group-label">今天稍后</p>
          {snapshot.today.map((item, index) => (
            <p key={`t-${index}`} className="snapshot-row">
              <span className="when">{formatDue(item.due_at)}</span>
              <span className="sep">·</span>{item.title}
              <span className="repeat">（{item.repeat}）</span>
            </p>
          ))}
        </div>
      )}
      {snapshot.omitted > 0 && (
        <p className="snapshot-more">还有 {snapshot.omitted} 项未展开，请到任务页查看。</p>
      )}
    </div>
  )
}
