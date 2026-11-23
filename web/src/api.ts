// Typed wrappers around bridge.invoke (protocol: docs/BRIDGE_API.md).

import { invoke, on, cancelJob } from './bridge/bridge'

export type Settings = {
  base_url?: string
  model?: string
  active_session?: string
  density?: 'comfortable' | 'compact'
  dnd_start?: string
  dnd_end?: string
  stream?: boolean
  remember_key?: boolean
  pet_paused?: boolean
  pet_walking?: boolean
  pet_mode?: '2d' | '3d'
  theme?: 'light' | 'dark'
  early_nudge?: boolean
  sound_enabled?: boolean
  auto_postpone?: boolean
  dnd_enabled?: boolean
  web_search_enabled?: boolean
  knowledge_enabled?: boolean
  pet_images?: { image: string; original?: string }[]
  pet_position?: [number, number]
}

export type SecretsStatus = {
  hasApiKey: boolean
  hasTavily: boolean
  hasDingtalk: boolean
  rememberKey: boolean
}

export type KnowledgeDoc = {
  doc_id: string
  name: string
  source_path?: string
  page_count?: number
  added_at?: string
  wiki_error?: string
}

export type KnowledgeJobResult = {
  jobId: string
  cancelled: boolean
  added: number
  updated: number
  skipped: number
  failed: number
  message: string
}

export type AssessmentQuestion = {
  id: string
  number: number
  category: string
  prompt: string
  guide: string
  reference: string
  max_score: number
  answer: string
  score: number | null
  feedback: string
  reviewed: boolean
  image_count: number
}

export type AssessmentImage = {
  id: string
  name: string
  path?: string
  question_id: string
  transcription: string
  role: 'reference' | 'answer' | 'unclassified'
}

export type AssessmentResult = {
  question_id: string
  score: number
  max_score: number
  feedback: string
  evidence: string
  criteria: { item: string; met: boolean; reason: string }[]
}

export type AssessmentRun = {
  id: string
  assessment_id: string
  status: string
  answers: Record<string, string>
  results: AssessmentResult[]
  score: number
  max_score: number
  created_at: string
  candidate_name: string
}

export type Assessment = {
  id: string
  title: string
  source_name: string
  overview: string
  declared_score: number
  image_count: number
  questions: AssessmentQuestion[]
  images: AssessmentImage[]
  runs: AssessmentRun[]
  run_count?: number
  question_count?: number
}

export type KnowledgeJobProgress = { jobId: string; message: string }
export type GradeJobResult = {
  jobId: string
  ok: boolean
  run?: AssessmentRun
  cancelled?: boolean
  message: string
}
export type KnowledgeVisionResult = {
  jobId: string
  ok: boolean
  cancelled?: boolean
  assessmentId?: string
  imageId?: string
  text?: string
  message: string
}
export type AssessmentImportResult = {
  jobId: string | null
  assessmentId: string
  completed: number
  failed: { imageId: string; name: string; error: string }[]
  cancelled: boolean
  message: string
}

export type ConnectionTestResult = {
  jobId: string
  kind: 'model' | 'tavily' | 'dingtalk'
  ok: boolean
  message: string
}

export type PetImageItem = {
  image: string
  original: string
  thumb: string
  active: boolean
}

export type PetGallery = {
  active: string
  items: PetImageItem[]
  defaultThumb: string
  preview: string
  hasOriginal: boolean
  position: number[]
}

export type SystemInfo = {
  appVersion: string
  bridgeVersion: number
  platform: string
  devMode: boolean
  dataDir: string
}

export type RepeatRule = 'none' | 'daily' | 'weekdays' | 'weekly'
export type Horizon = 'timed' | 'week' | 'month' | 'someday'

export type Task = {
  id: string
  title: string
  due_at: string | null
  created_at: string
  repeat_rule: RepeatRule
  scheduled_at: string | null
  dingtalk: number
  source: string
  note: string
  status: 'pending' | 'done' | string
  notified_at: string | null
  remind_count: number
  deferred: number
  completed_at: string | null
  early_notified_at: string | null
  muted_until: string | null
  next_id: string | null
  horizon: Horizon
  remind_at: string | null
}

export type TaskEvent = {
  id: number
  task_id: string
  kind: string
  at: string
  detail: string
  title: string | null
}

export type TodayStats = {
  completed_today: number
  reminders_today: number
  on_time_rate: number | null
  week_on_time_days: number
  week_on_time_dates: string[]
}

export type ReminderTask = Task & {
  final?: boolean
  minutesLeft?: number
}

export type Draft = {
  id: string
  title: string
  due_at: string
  created_at: string
  session_id: string
  repeat_rule: RepeatRule
  note: string
}

export type ChatSession = {
  id: string
  title: string
  updatedAt: string
  messageCount: number
}

export type ChatMessage = {
  role: 'user' | 'assistant' | 'system' | string
  content: string
  created_at?: string
}

export type SnapshotItem = {
  title: string
  due_at: string
  repeat: string
}

export type ChatSnapshot = {
  at: string
  overdue_count: number
  today_count: number
  future_count: number
  overdue: SnapshotItem[]
  today: SnapshotItem[]
  omitted: number
}

export type SearchSource = {
  title: string
  url: string
  content?: string
  published_date?: string
}

export type KnowledgeHit = {
  doc_id?: string
  doc_name?: string
  title?: string
  kind?: string
  text?: string
}

export type AssistantStateName =
  | 'idle' | 'searching' | 'knowledge' | 'responding' | 'stopped' | 'failed'

export type AssistantState = {
  state: AssistantStateName
  jobId?: string | null
  sessionId?: string | null
  sources?: SearchSource[]
  knowledge?: KnowledgeHit[]
}

export type AssistantChunk = {
  jobId?: string | null
  sessionId?: string | null
  text: string
}

export type AssistantResult = {
  jobId?: string | null
  sessionId: string
  reply: string
  tasks: string[]
  errors: string[]
  choice: string | null
  note: string
  notices: string[]
  sources: SearchSource[]
  knowledge: KnowledgeHit[]
  meta: string
}

export type AssistantFailed = {
  jobId?: string | null
  sessionId?: string | null
  message: string
  retryable?: boolean
}

export type PlanResult = {
  snapshot: ChatSnapshot
  reply: string
  jobId?: string | null
  sessionId?: string | null
}

export type ChatSessionPayload = {
  activeSession: string
  session: { id: string; title: string; inputText: string }
  messages: ChatMessage[]
  drafts: Draft[]
  canRegenerate: boolean
  retryable: boolean
  busy: boolean
  busySessionId: string | null
  hasModel: boolean
  choicePending: boolean
}

export type ChatPlanPreview = {
  snapshot: ChatSnapshot
  prompt: string
  usesModel: boolean
  activeSession: string
}

export const api = {
  systemInfo: () => invoke<SystemInfo>('system.info'),
  pickFiles: (title: string, filter: string) =>
    invoke<{ paths: string[] }>('system.pickFiles', { title, filter }),
  pickFolder: (title: string) => invoke<{ path: string | null }>('system.pickFolder', { title }),
  pickSavePath: (name: string, filter: string, extension: string) =>
    invoke<{ path: string | null }>('system.pickSavePath', { name, filter, extension }),
  writeTextFile: (name: string, text: string) => invoke<{ file: string | null; cancelled?: boolean }>('system.writeTextFile', { name, text, title: '导出测评报告', filter: 'Markdown 文件 (*.md)', extension: '.md' }),
  openDataDir: () => invoke<void>('system.openPath'),
  getSettings: () => invoke<Settings>('settings.getAll'),
  setSettings: (patch: Partial<Settings>) =>
    invoke<void>('settings.set', { patch: patch as Record<string, unknown> }),
  exportData: (path: string) =>
    invoke<{ file: string; tasks: number; sessions: number }>('settings.exportData', { path }),
  clearData: () => invoke<{ backup: string | null }>('settings.clearData'),
  getSecretsStatus: () => invoke<SecretsStatus>('secrets.status'),
  saveApiKey: (endpoint: string, value: string) =>
    invoke<void>('secrets.saveApiKey', { endpoint, value }),
  saveTavily: (value: string) => invoke<void>('secrets.saveTavily', { value }),
  saveDingtalk: (webhook: string, secret: string) =>
    invoke<void>('secrets.saveDingtalk', { webhook, secret }),
  setRememberKey: (enabled: boolean) => invoke<void>('secrets.rememberKey', { enabled }),
  testConnection: (kind: 'model' | 'tavily' | 'dingtalk', extra: Record<string, unknown> = {}) =>
    invoke<{ jobId: string }>('secrets.testConnection', { kind, ...extra }),
  getStartup: () => invoke<{ enabled: boolean }>('startup.get'),
  setStartup: (enabled: boolean) => invoke<void>('startup.set', { enabled }),
  knowledgeDocs: () => invoke<{ documents: KnowledgeDoc[] }>('knowledge.documents'),
  knowledgeStats: () => invoke<Record<string, number>>('knowledge.stats'),
  knowledgeSearch: (query: string) => invoke<{ hits: KnowledgeHit[] }>('knowledge.search', { query }),
  knowledgeImage: (imageId: string) =>
    invoke<{ id: string; mime: string; data: string }>('knowledge.image', { imageId }),
  knowledgeRemove: (docId: string) => invoke<void>('knowledge.remove', { docId }),
  knowledgeClear: () => invoke<void>('knowledge.clear'),
  knowledgeImportPaths: (paths: string[]) =>
    invoke<{ jobId: string }>('knowledge.importPaths', { paths }),
  knowledgeRebuild: (docId: string) => invoke<{ jobId: string }>('knowledge.rebuild', { docId }),
  knowledgeAssessments: () => invoke<{ assessments: Assessment[] }>('knowledge.assessments'),
  knowledgeAssessment: (assessmentId: string) => invoke<Assessment>('knowledge.assessment', { assessmentId }),
  knowledgeImportAssessment: (path: string) => invoke<{ assessment: Assessment; jobId: string | null; visionSkipped: boolean }>('knowledge.importAssessment', { path }),
  knowledgeSaveAssessment: (assessmentId: string, title: string, questions: AssessmentQuestion[]) =>
    invoke<Assessment>('knowledge.saveAssessment', { assessmentId, title, questions }),
  knowledgeDeleteAssessment: (assessmentId: string) => invoke<void>('knowledge.deleteAssessment', { assessmentId }),
  knowledgeAssessmentImage: (assessmentId: string, imageId: string) =>
    invoke<{ id: string; mime: string; data: string }>('knowledge.assessmentImage', { assessmentId, imageId }),
  knowledgeRecognizeImage: (assessmentId: string, imageId: string) =>
    invoke<{ jobId: string }>('knowledge.recognizeAssessmentImage', { assessmentId, imageId }),
  knowledgeSaveAssessmentImage: (assessmentId: string, imageId: string) =>
    invoke<{ file: string | null; cancelled?: boolean }>('knowledge.assessmentImageFile', { assessmentId, imageId }),
  knowledgeSaveImageTranscription: (assessmentId: string, imageId: string, questionId: string, transcription: string, role: AssessmentImage['role']) =>
    invoke<AssessmentImage>('knowledge.saveImageTranscription', { assessmentId, imageId, questionId, transcription, role }),
  knowledgeGrade: (assessmentId: string, answers: Record<string, string>, candidateName = '') =>
    invoke<{ jobId: string }>('knowledge.gradeAssessment', { assessmentId, answers, candidateName }),
  knowledgeUpdateRun: (runId: string, results: AssessmentResult[]) =>
    invoke<AssessmentRun>('knowledge.updateAssessmentRun', { runId, results }),
  knowledgeDeleteRun: (runId: string) => invoke<void>('knowledge.deleteAssessmentRun', { runId }),
  knowledgeExportRun: (runId: string) => invoke<{ markdown: string }>('knowledge.exportAssessmentRun', { runId }),
  petGallery: () => invoke<PetGallery>('pet.gallery'),
  petSelect: (image: string) => invoke<{ applied: boolean }>('pet.select', { image }),
  petChooseImage: () => invoke<{ changed: boolean }>('pet.chooseImage'),
  petRemoveImage: () => invoke<{ changed: boolean }>('pet.removeImage'),
  petRemoveBackground: () => invoke<{ changed: boolean }>('pet.removeBackground'),
  petRestoreOriginal: () => invoke<{ changed: boolean }>('pet.restoreOriginal'),
  petResetPosition: () => invoke<void>('pet.resetPosition'),
  tasksList: () => invoke<Task[]>('tasks.list'),
  tasksHistory: (status: 'done' = 'done', search = '') =>
    invoke<Task[]>('tasks.history', { status, search }),
  taskAdd: (payload: {
    title: string
    dueAt?: string | null
    horizon?: Horizon
    repeat?: RepeatRule
    dingtalk?: boolean
    note?: string
  }) => invoke<Task>('tasks.add', payload),
  taskEdit: (payload: {
    id: string
    title: string
    dueAt?: string | null
    horizon?: Horizon
    repeat?: RepeatRule
    dingtalk?: boolean
  }) => invoke<Task>('tasks.edit', payload),
  taskComplete: (id: string) => invoke<{ nextId: string | null }>('tasks.complete', { id }),
  taskReopen: (id: string) => invoke<void>('tasks.reopen', { id }),
  taskDelete: (id: string) => invoke<void>('tasks.delete', { id }),
  taskUndoDelete: (id: string) => invoke<void>('tasks.undoDelete', { id }),
  taskSnooze: (id: string, minutes = 10) => invoke<void>('tasks.snooze', { id, minutes }),
  taskSetDingtalk: (id: string, enabled: boolean) =>
    invoke<void>('tasks.setDingtalk', { id, enabled }),
  taskMuteToday: (id: string) => invoke<{ mutedUntil: string }>('tasks.muteToday', { id }),
  taskStats: () => invoke<TodayStats>('tasks.stats'),
  taskTodayEvents: () => invoke<TaskEvent[]>('tasks.todayEvents'),
  taskParseDue: (text: string) =>
    invoke<{ dueAt: string; repeat: RepeatRule; past: boolean }>('tasks.parseDue', { text }),
  taskDismissReminder: (id: string, postpone = true) =>
    invoke<{ postponed: boolean }>('tasks.dismissReminder', { id, postpone }),
  draftsList: (sessionId?: string) => invoke<Draft[]>('drafts.list', { sessionId }),
  draftSave: (payload: {
    id?: string
    title: string
    dueAt: string
    sessionId?: string
    repeat?: RepeatRule
    note?: string
  }) => invoke<{ id: string }>('drafts.save', payload),
  draftConfirm: (id: string) => invoke<{ taskId: string }>('drafts.confirm', { id }),
  draftDiscard: (id: string) => invoke<void>('drafts.discard', { id }),
  chatSessions: () =>
    invoke<{ activeSession: string; sessions: ChatSession[] }>('chat.sessions'),
  chatSession: (sessionId?: string, limit = 100) =>
    invoke<ChatSessionPayload>('chat.session', { sessionId, limit }),
  chatCreateSession: (title?: string) =>
    invoke<ChatSessionPayload & { sessionId: string }>('chat.createSession', { title }),
  chatDeleteSession: (sessionId: string) =>
    invoke<{ activeSession: string }>('chat.deleteSession', { sessionId }),
  chatRenameSession: (sessionId: string, title: string) =>
    invoke<void>('chat.renameSession', { sessionId, title }),
  chatSaveInput: (sessionId: string, text: string) =>
    invoke<void>('chat.saveInput', { sessionId, text }),
  chatSend: (sessionId: string, text: string) =>
    invoke<{ accepted: boolean; mode?: string; local?: boolean; jobId?: string }>(
      'chat.send', { sessionId, text }),
  chatRetry: (sessionId: string) =>
    invoke<{ accepted: boolean; jobId: string }>('chat.retry', { sessionId }),
  chatRegenerate: (sessionId: string) =>
    invoke<{ jobId: string; sessionId: string }>('chat.regenerate', { sessionId }),
  chatStop: () => invoke<{ stopped: boolean; jobId?: string }>('chat.stop'),
  chatChooseTask: (sessionId: string, index: number) =>
    invoke<{ reply: string }>('chat.chooseTask', { sessionId, index }),
  chatPlanPreview: (sessionId?: string) =>
    invoke<ChatPlanPreview>('chat.planToday', { confirmed: false, sessionId }),
  chatPlanStart: (sessionId?: string) =>
    invoke<{ accepted: boolean; jobId: string; snapshot: ChatSnapshot; local?: boolean }>(
      'chat.planToday', { confirmed: true, sessionId }),
  cancelJob,
}

export function onSettingsChanged(handler: (patch: Partial<Settings>) => void) {
  return on('settings.changed', (payload: { patch: Partial<Settings> }) => handler(payload.patch))
}

export function onConnectionTested(handler: (result: ConnectionTestResult) => void) {
  return on('connection.testResult', handler)
}

export function onKnowledgeProgress(handler: (payload: { jobId: string; message: string }) => void) {
  return on('knowledge.jobProgress', handler)
}

export function onKnowledgeDone(handler: (payload: KnowledgeJobResult) => void) {
  return on('knowledge.jobDone', handler)
}

export function onKnowledgeGradeDone(handler: (payload: GradeJobResult) => void) {
  return on('knowledge.gradeDone', handler)
}

export function onKnowledgeVisionDone(handler: (payload: KnowledgeVisionResult) => void) {
  return on('knowledge.visionDone', handler)
}

export function onAssessmentImportDone(handler: (payload: AssessmentImportResult) => void) {
  return on('knowledge.assessmentImportDone', handler)
}

export function onPetChanged(handler: (payload: { active: string; changed: boolean }) => void) {
  return on('pet.changed', handler)
}

export function onTasksChanged(handler: (payload: { reason: string }) => void) {
  return on('tasks.changed', handler)
}

export function onReminderDue(handler: (payload: { tasks: ReminderTask[] }) => void) {
  return on('reminder.due', handler)
}

export function onReminderEarly(handler: (payload: { tasks: ReminderTask[] }) => void) {
  return on('reminder.early', handler)
}

export function onNavigate(handler: (payload: { page: string }) => void) {
  return on('ui.navigate', handler)
}

export function onAssistantState(handler: (payload: AssistantState) => void) {
  return on('assistant.state', handler)
}

export function onAssistantChunk(handler: (payload: AssistantChunk) => void) {
  return on('assistant.chunk', handler)
}

export function onAssistantResult(handler: (payload: AssistantResult) => void) {
  return on('assistant.result', handler)
}

export function onAssistantFailed(handler: (payload: AssistantFailed) => void) {
  return on('assistant.failed', handler)
}

export function onPlanResult(handler: (payload: PlanResult) => void) {
  return on('plan.result', handler)
}

export function onChatChanged(
  handler: (payload: { reason: string; sessionId?: string; title?: string; messageCount?: number }) => void,
) {
  return on('chat.changed', handler)
}
