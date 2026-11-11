// QWebChannel client. The whole web UI talks to Python exclusively through this file
// (protocol: docs/BRIDGE_API.md).

export type Envelope = { ok: true; data: any } | { ok: false; error: { code: string; message: string } }

export class BridgeError extends Error {
  readonly code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

type EventHandler = (payload: any) => void
type AnyHandler = (name: string, payload: any) => void

interface QtBridge {
  invoke(method: string, payload: string, callback: (response: string) => void): void
  cancel(jobId: string): void
  event: { connect(callback: (name: string, payload: string) => void): void }
}

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown }
    QWebChannel?: new (transport: unknown, callback: (channel: { objects: { bridge: QtBridge } }) => void) => void
  }
}

let qtBridge: QtBridge | null = null
const handlers = new Map<string, Set<EventHandler>>()
const anyHandlers = new Set<AnyHandler>()

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const el = document.createElement('script')
    el.src = src
    el.onload = () => resolve()
    el.onerror = () => reject(new Error(`脚本加载失败: ${src}`))
    document.head.appendChild(el)
  })
}

function dispatchEvent(name: string, raw: string) {
  let payload: any
  try {
    payload = JSON.parse(raw)
  } catch {
    payload = raw
  }
  handlers.get(name)?.forEach((h) => h(payload))
  anyHandlers.forEach((h) => h(name, payload))
}

export async function connectBridge(): Promise<void> {
  if (qtBridge) return
  if (!window.qt?.webChannelTransport || !window.QWebChannel) {
    if (!window.qt?.webChannelTransport) {
      throw new BridgeError('NOT_AVAILABLE', '桥不可用：请在桌面宠物壳内运行。')
    }
    // qwebchannel.js is compiled into the Qt resources; no vendored copy exists on disk.
    await loadScript('qrc:///qtwebchannel/qwebchannel.js')
  }
  await new Promise<void>((resolve, reject) => {
    if (!window.QWebChannel) {
      reject(new BridgeError('NOT_AVAILABLE', 'QWebChannel 未加载'))
      return
    }
    new window.QWebChannel(window.qt!.webChannelTransport, (channel) => {
      qtBridge = channel.objects.bridge
      qtBridge.event.connect((name, payload) => dispatchEvent(name, payload))
      resolve()
    })
  })
}

function requireBridge(): QtBridge {
  if (!qtBridge) throw new BridgeError('NOT_AVAILABLE', '桥尚未连接')
  return qtBridge
}

export function invoke<T = any>(method: string, args: Record<string, unknown> = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    requireBridge().invoke(method, JSON.stringify(args), (response) => {
      const env = JSON.parse(response) as Envelope
      if (env.ok) resolve(env.data)
      else reject(new BridgeError(env.error.code, env.error.message))
    })
  })
}

export function cancelJob(jobId: string) {
  requireBridge().cancel(jobId)
}

export function on(name: string, handler: EventHandler) {
  let set = handlers.get(name)
  if (!set) {
    set = new Set()
    handlers.set(name, set)
  }
  set.add(handler)
  return () => {
    set!.delete(handler)
  }
}

export function onAny(handler: AnyHandler) {
  anyHandlers.add(handler)
  return () => {
    anyHandlers.delete(handler)
  }
}
