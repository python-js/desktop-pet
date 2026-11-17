import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  api, AssistantResult, AssistantState, ChatMessage, ChatPlanPreview, ChatSession,
  ChatSessionPayload, ChatSnapshot, Draft, KnowledgeHit, PlanResult, SearchSource, Task,
  onAssistantChunk, onAssistantFailed, onAssistantResult, onAssistantState,
  onChatChanged, onPlanResult, onTasksChanged,
} from '../api'
import { fetchCached, invalidateCache, isFresh, readCache, writeCache } from '../queryCache'
import { Button, Icon, Paw, Pill } from '../ui'
import { formatClock, formatDue, isToday, REPEAT_LABELS } from '../tasks'
import Markdown from '../components/Markdown'
import LatticeLoader from '../components/LatticeLoader'
import GlideSelect from '../components/GlideSelect'
import SpecularButton from '../components/SpecularButton'

type UiMessage = ChatMessage & {
  sources?: SearchSource[]
  knowledge?: KnowledgeHit[]
  meta?: string
  tasks?: string[]
  choice?: string | null
}

function formatMessageTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const clock = formatClock(value)
  return date.toDateString() === now.toDateString()
    ? `今天 ${clock}`
    : `${date.getMonth() + 1}月${date.getDate()}日 ${clock}`
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
  active?: boolean
}) {
  const initialSessionId = readCache<string>('chat.activeSession') ?? ''
  const initialPayload = initialSessionId
    ? readCache<ChatSessionPayload>(`chat.session.${initialSessionId}`) ?? null
    : null
  const [sessions, setSessions] = useState<ChatSession[]>(() => readCache<ChatSession[]>('chat.sessions') ?? [])
  const [sideTasks, setSideTasks] = useState<Task[]>(() => readCache<Task[]>('tasks.pending') ?? [])
  const [active, setActive] = useState(initialSessionId)
  const [payload, setPayload] = useState<ChatSessionPayload | null>(initialPayload)
  const [messages, setMessages] = useState<UiMessage[]>(() => initialPayload?.messages.map((message) => ({ ...message })) ?? [])
  const [drafts, setDrafts] = useState<Draft[]>(() => initialPayload?.drafts ?? [])
  const [input, setInput] = useState(() => initialPayload?.session.inputText ?? '')
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
  const [createPending, setCreatePending] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(!initialPayload)
  const [refreshing, setRefreshing] = useState(false)

  const activeRef = useRef('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const streamContentRef = useRef<HTMLDivElement>(null)
  const bottomAnchorRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const stickRef = useRef(true)
  const loadRequestRef = useRef(0)

  const applySession = useCallback((data: ChatSessionPayload) => {
    const switching = activeRef.current !== data.session.id
    activeRef.current = data.session.id
    writeCache('chat.activeSession', data.session.id)
    setActive(data.session.id)
    setPayload(data)
    setMessages(data.messages.map((message) => ({ ...message })))
    setDrafts(data.drafts)
    // 同一会话的后台同步不覆盖输入框，否则发送后会被服务端旧文本回填。
    if (switching) setInput(data.session.inputText)
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

  const loadSession = useCallback(async (sessionId?: string) => {
    const requestId = ++loadRequestRef.current
    const cached = sessionId ? readCache<ChatSessionPayload>(`chat.session.${sessionId}`) : undefined
    if (cached) applySession(cached)
    setInitialLoading(!cached)
    setRefreshing(!!cached)
    try {
      if (cached && isFresh(`chat.session.${sessionId}`, 15_000)) {
        // Reuse fresh messages immediately while still activating the session in the shell.
        const activated = await api.chatSession(sessionId)
        writeCache(`chat.session.${activated.session.id}`, activated)
        if (requestId === loadRequestRef.current) applySession(activated)
      } else {
        const data = await api.chatSession(sessionId)
        writeCache(`chat.session.${data.session.id}`, data)
        if (requestId === loadRequestRef.current) applySession(data)
      }
    } finally {
      if (requestId === loadRequestRef.current) {
        setInitialLoading(false)
        setRefreshing(false)
      }
    }
  }, [applySession])

  const refreshSessions = useCallback(async () => {
    try {
      const data = await api.chatSessions()
      writeCache('chat.sessions', data.sessions)
      setSessions(data.sessions)
    } catch {
      // Session list refresh is best-effort; the next event retries.
    }
  }, [])

  useEffect(() => {
    if (!props.active) return
    const cachedSessions = readCache<ChatSession[]>('chat.sessions')
    const cachedActive = readCache<string>('chat.activeSession')
    const cachedSession = cachedActive
      ? readCache<ChatSessionPayload>(`chat.session.${cachedActive}`)
      : undefined
    if (cachedSessions && cachedSession && isFresh('chat.sessions', 15_000)
      && isFresh(`chat.session.${cachedActive}`, 15_000)) {
      setSessions(cachedSessions)
      applySession(cachedSession)
      setInitialLoading(false)
      setRefreshing(false)
      return
    }
    if (cachedSessions) setSessions(cachedSessions)
    if (cachedSession) {
      applySession(cachedSession)
      setInitialLoading(false)
    }
    let cancelled = false
    void (async () => {
      try {
        if (!cachedSession) setInitialLoading(true)
        const data = await api.chatSessions()
        if (cancelled) return
        invalidateCache('chat.sessions')
        data.sessions.forEach((session) => invalidateCache(`chat.session.${session.id}`))
        writeCache('chat.sessions', data.sessions)
        setSessions(data.sessions)
        await loadSession(data.activeSession)
      } catch (err) {
        if (!cancelled) {
          setInitialLoading(false)
          setNotice(err instanceof Error ? err.message : '读取对话失败')
        }
      }
    })()
    return () => { cancelled = true }
  }, [applySession, loadSession, props.active])

  useEffect(() => {
    if (!props.active) return
    const load = () => {
      invalidateCache('tasks.pending')
      void fetchCached('tasks.pending', api.tasksList)
        .then((rows) => setSideTasks(rows))
        .catch(() => {})
    }
    load()
    return onTasksChanged(load)
  }, [props.active])

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
      created_at: new Date().toISOString(),
      sources: result.sources,
      knowledge: result.knowledge,
      meta: result.meta,
      tasks: result.tasks,
      choice: result.choice,
    }
    setMessages((prev) => {
      const next = [...prev, message]
      const createdAt = new Date().toISOString()
      if (result.note) next.push({ role: 'system', content: result.note, created_at: createdAt })
      result.notices.forEach((text) => next.push({ role: 'system', content: text, created_at: createdAt }))
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
  useEffect(() => onChatChanged((event) => {
    invalidateCache('chat.sessions')
    if (event.sessionId) invalidateCache(`chat.session.${event.sessionId}`)
    if (!props.active) return
    void refreshSessions()
    // 当前会话的消息已由乐观追加与 assistant.result/回执维护；
    // 整栏重取会闪加载骨架并回写服务端旧输入，这里只同步会话列表。
  }), [props.active, refreshSessions])

  // Persist the unsent composer text so a page reload or session switch keeps it.
  useEffect(() => {
    if (!active) return
    const timer = window.setTimeout(() => {
      void api.chatSaveInput(active, input).catch(() => {})
    }, 400)
    return () => window.clearTimeout(timer)
  }, [input, active])

  useEffect(() => {
    if (!active || !payload) return
    const cached = readCache<ChatSessionPayload>(`chat.session.${active}`)
    if (cached) {
      writeCache(`chat.session.${active}`, {
        ...cached,
        session: { ...cached.session, inputText: input },
      })
    }
  }, [input, active, payload])

  const stream = streams[active]
  const streamText = stream?.text ?? ''
  const busy = BUSY_STATES.has(state.state)
  const otherBusy = busy && !!state.sessionId && state.sessionId !== active
  const waitingForReply = busy && state.sessionId === active && !streamText
  const scrollToBottom = useCallback(() => {
    const anchor = bottomAnchorRef.current
    if (anchor) {
      anchor.scrollIntoView({ block: 'end', behavior: 'auto' })
      return
    }
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  useLayoutEffect(() => {
    if (!stickRef.current && !waitingForReply) return
    scrollToBottom()
    const frame = window.requestAnimationFrame(() => {
      if (stickRef.current || waitingForReply) scrollToBottom()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [messages, streamText, planCard, drafts, active, busy, state.sessionId, waitingForReply, scrollToBottom])

  useEffect(() => {
    const content = streamContentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (!stickRef.current && !waitingForReply) return
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        if (stickRef.current || waitingForReply) scrollToBottom()
      })
    })
    observer.observe(content)
    return () => {
      observer.disconnect()
      window.cancelAnimationFrame(frame)
    }
  }, [active, waitingForReply, scrollToBottom])

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
    if (waitingForReply) return
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
    setMessages((prev) => [...prev, { role: 'user', content: text, created_at: new Date().toISOString() }])
    setInput('')
    // 立即持久化空输入，避免后台同步在防抖窗口内读回旧草稿。
    void api.chatSaveInput(activeRef.current, '').catch(() => {})
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
    if (createPending || sessions[0]?.messageCount === 0) return
    setCreatePending(true)
    try {
      const data = await api.chatCreateSession()
      await refreshSessions()
      await loadSession(data.sessionId)
    } finally {
      setCreatePending(false)
    }
  })

  const deleteSession = (sessionId: string) => setDeleteConfirm(sessionId)

  const confirmDeleteSession = () => void act('删除对话', async () => {
    if (!deleteConfirm) return
    const sessionId = deleteConfirm
    setDeleteConfirm(null)
    const result = await api.chatDeleteSession(sessionId)
    await refreshSessions()
    if (sessionId === activeRef.current) await loadSession(result.activeSession)
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
    setMessages((prev) => [...prev, { role: 'user', content: '帮我规划今天', created_at: new Date().toISOString() }])
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
      {refreshing && !initialLoading && <div className="page-refresh-indicator chat-refresh-indicator"><i />正在同步</div>}
      {initialLoading && <div className="page-skeleton chat-skeleton" aria-label="正在加载对话"><span /><span /><span /></div>}
      <div className="chat">
        <section className="chat-main">
          <header className="chat-head">
            <div className="chat-heading">
              <span className="chat-heading-mark"><Paw size={17} /></span>
              <div className="chat-heading-copy">
                <span className="chat-head-label">YOUR THOUGHT PARTNER</span>
                <strong>对话助手</strong>
                <span className="chat-heading-subtitle">把想法理清楚，再一步步变成行动</span>
              </div>
            </div>
            <div className="chat-toolbar">
              <div className="chat-session-control">
                <span className="chat-session-caption">当前会话</span>
                {editing ? (
                  <input
                    className="field chat-session-edit"
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
                  <GlideSelect
                    className="chat-session-glide"
                    ariaLabel="切换当前对话"
                    value={active}
                    options={sessions.map((session) => ({
                      value: session.id,
                      label: session.title,
                      description: `${session.messageCount} 条消息`,
                    }))}
                    renderOptionActions={(sessionId) => sessionId !== 'default' ? (
                      <button
                        type="button"
                        className="chat-session-delete"
                        title="删除此对话"
                        aria-label={`删除${sessions.find((session) => session.id === sessionId)?.title ?? '对话'}`}
                        disabled={busy && state.sessionId === sessionId}
                        onClick={(event) => {
                          event.stopPropagation()
                          if (busy && state.sessionId === sessionId) return
                          deleteSession(sessionId)
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            event.stopPropagation()
                            if (busy && state.sessionId === sessionId) return
                            deleteSession(sessionId)
                          }
                        }}
                      ><Icon name="trash" size={13} /></button>
                    ) : null}
                    onChange={(sessionId) => {
                      if (sessionId !== active) void act('切换对话', () => loadSession(sessionId))
                    }}
                  />
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
              </div>
              <Button small onClick={previewPlan} disabled={busy}>
                <Icon name="sparkles" size={14} />今日规划
              </Button>
              <Button small primary onClick={createSession} disabled={createPending || sessions[0]?.messageCount === 0}>
                <Icon name="plus" size={14} />新对话
              </Button>
            </div>
          </header>

          <div ref={scrollRef} onScroll={onScroll} className="chat-stream">
            <div ref={streamContentRef} className="chat-stream-content">
            {messages.length === 0 && !streamText && drafts.length === 0 && (
              <div className="chat-empty">
                <span className="rail-logo"><Paw size={22} /></span>
                <p className="chat-empty-title">和小满聊聊今天要做什么</p>
                <p className="chat-empty-text">
                  记下一闪而过的想法，安排时间，或者一起把今天理出头绪。
                </p>
                <div className="chat-starters" aria-label="试试这样开始">
                  {[
                    '帮我安排今天的优先事项',
                    '明天下午 3 点提醒我给客户回电话',
                    '把我这周要做的事整理一下',
                  ].map((prompt, index) => (
                    <button
                      key={prompt}
                      type="button"
                      className="chat-starter"
                      onClick={() => {
                        setInput(prompt)
                        inputRef.current?.focus()
                      }}
                    >
                      <span className="chat-starter-index">0{index + 1}</span>
                      <span>{prompt}</span>
                      <Icon name="chevron-down" size={13} />
                    </button>
                  ))}
                </div>
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
            <div ref={bottomAnchorRef} className="chat-bottom-anchor" aria-hidden="true" />
            </div>
          </div>

          <footer className="composer">
            <div className="composer-prompt-label">
              <span className="composer-prompt-dot" />
              <span>和小满说说你的安排</span>
              <span className="composer-prompt-hint">支持自然语言记录与规划</span>
            </div>
            <textarea
              ref={inputRef}
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
                <SpecularButton className="composer-send-button" disabled={!input.trim() || sending} onClick={() => void send()}>
                  <Icon name="send" size={13} />发送
                </SpecularButton>
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

      {deleteConfirm && createPortal((
        <div className="chat-delete-backdrop" role="presentation" onPointerDown={(event) => { if (event.target === event.currentTarget) setDeleteConfirm(null) }}>
          <section className="chat-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="chat-delete-title">
            <h2 id="chat-delete-title">删除这段对话？</h2>
            <p>“{sessions.find((session) => session.id === deleteConfirm)?.title ?? '对话'}”中的消息和未提交的待办草稿都会被永久删除。</p>
            <div>
              <Button onClick={() => setDeleteConfirm(null)}>取消</Button>
              <Button danger onClick={confirmDeleteSession}>删除对话</Button>
            </div>
          </section>
        </div>
      ), document.body)}
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
        {message.created_at && <time className="msg-time">{formatMessageTime(message.created_at)}</time>}
        <span><Icon name="check" size={11} />{message.content}</span>
      </div>
    )
  }
  if (message.role === 'user') {
    return (
      <div className="msg user">
        <div className="msg-body msg-body-user">
          {message.created_at && <time className="msg-time msg-time-user">{formatMessageTime(message.created_at)}</time>}
          <div className="bubble-user">{message.content}</div>
        </div>
        <span className="msg-user-avatar" aria-label="我">我</span>
      </div>
    )
  }
  const choices = message.choice ? choiceCount(message.choice) : 0
  return (
    <div className="msg">
      <span className="msg-avatar" aria-label="小满"><Paw size={15} /><i /></span>
      <div className="msg-body">
        {message.created_at && <time className="msg-time">{formatMessageTime(message.created_at)}</time>}
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
        </div>
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
    <div className={`msg${props.text ? '' : ' msg-thinking'}`}>
      <span className="msg-avatar" aria-label="小满"><Paw size={15} /><i /></span>
      <div className="msg-body">
        <div className="bubble streaming">
          {props.text
            ? <Markdown text={props.text} />
            : <LatticeLoader label={props.status || '正在思考…'} />}
          <Materials sources={props.sources} knowledge={props.knowledge} />
          {props.text && <p className="msg-meta" style={{ marginTop: 5 }}>{props.status}</p>}
        </div>
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
    createPortal(<div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="今日规划预览">
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
    </div>, document.body)
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
