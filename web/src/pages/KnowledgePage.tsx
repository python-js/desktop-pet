import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api, Assessment, AssessmentImage, AssessmentQuestion, AssessmentRun,
  GradeJobResult, KnowledgeDoc, KnowledgeHit, KnowledgeJobResult, onKnowledgeDone, onKnowledgeGradeDone,
  AssessmentImportResult, KnowledgeVisionResult, onAssessmentImportDone,
  onKnowledgeProgress, onKnowledgeVisionDone,
} from '../api'
import { BridgeError } from '../bridge/bridge'
import { Button, Icon, Pill, StatusLine, Toggle } from '../ui'

const KNOWLEDGE_FILTER = '支持的资料 (*.pdf *.docx *.xlsx *.xlsm *.txt *.md *.markdown *.csv *.json *.log *.yaml *.yml);;所有文件 (*.*)'
const ASSESSMENT_FILTER = 'Word 文档 (*.docx)'

type Tab = 'library' | 'assessment'

function messageOf(error: unknown) {
  return error instanceof BridgeError || error instanceof Error ? error.message : '操作失败，请重试。'
}

function queryTerms(query: string, size: number, wordMin: number) {
  const terms: string[] = []
  for (const word of query.match(/[A-Za-z0-9][A-Za-z0-9_+.#-]{1,}/g) ?? []) {
    if (word.length >= wordMin) terms.push(word)
  }
  for (const run of query.match(/[\u4e00-\u9fff]{2,}/g) ?? []) {
    for (let index = 0; index + size <= run.length; index += 1) terms.push(run.slice(index, index + size))
  }
  return terms
}

function mergeRanges(text: string, terms: string[]) {
  const lower = text.toLowerCase()
  const spans: Array<[number, number]> = []
  for (const term of terms) {
    const needle = term.toLowerCase()
    for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, at + needle.length)) {
      spans.push([at, at + needle.length])
    }
  }
  spans.sort((a, b) => a[0] - b[0])
  const merged: Array<[number, number]> = []
  for (const [start, end] of spans) {
    const last = merged[merged.length - 1]
    if (last && start <= last[1] + 1) last[1] = Math.max(last[1], end)
    else merged.push([start, end])
  }
  return merged
}

function hitRanges(text: string, query: string) {
  // 与索引一致：先用中文 3-gram/英文词，命中不到再退回 2-gram。
  const ranges = mergeRanges(text, queryTerms(query, 3, 3))
  return ranges.length ? ranges : mergeRanges(text, queryTerms(query, 2, 2))
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const ranges = query ? hitRanges(text, query) : []
  if (!ranges.length) return <>{text}</>
  const parts: ReactNode[] = []
  let cursor = 0
  for (const [start, end] of ranges) {
    if (start > cursor) parts.push(text.slice(cursor, start))
    parts.push(<mark key={start} className="knowledge-hit-mark">{text.slice(start, end)}</mark>)
    cursor = end
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

export default function KnowledgePage(props: {
  settings: { knowledge_enabled?: boolean; base_url?: string; model?: string }
  onSettings: (patch: { knowledge_enabled?: boolean }) => void
  active: boolean
}) {
  const [tab, setTab] = useState<Tab>('library')
  const [docs, setDocs] = useState<KnowledgeDoc[]>([])
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [run, setRun] = useState<AssessmentRun | null>(null)
  const [candidateName, setCandidateName] = useState('')
  const [status, setStatus] = useState('')
  const [tone, setTone] = useState<'plain' | 'calm' | 'alert'>('plain')
  const [busy, setBusy] = useState(false)
  const [selectedImage, setSelectedImage] = useState<AssessmentImage | null>(null)
  const [recognizedDraft, setRecognizedDraft] = useState<{ imageId: string; text: string } | null>(null)
  const [imagePreview, setImagePreview] = useState('')
  const [search, setSearch] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchHits, setSearchHits] = useState<KnowledgeHit[]>([])
  const jobId = useRef('')
  const visionJobId = useRef('')
  const assessmentImportJobId = useRef('')

  const refresh = useCallback(async (withSelectedAssessment = true) => {
    try {
      const [docsResult, assessmentResult] = await Promise.all([
        api.knowledgeDocs(), api.knowledgeAssessments(),
      ])
      setDocs(docsResult.documents)
      setAssessments(assessmentResult.assessments)
      setSelectedDoc((current: string | null) => current && docsResult.documents.some((doc) => doc.doc_id === current)
        ? current : docsResult.documents[0]?.doc_id ?? null)
      if (withSelectedAssessment && assessment?.id) {
        const current = await api.knowledgeAssessment(assessment.id)
        setAssessment(current)
        if (run?.id) setRun(current.runs.find((item) => item.id === run.id) ?? null)
      }
    } catch (error) {
      setStatus(messageOf(error))
      setTone('alert')
    }
  }, [assessment?.id, run?.id])

  useEffect(() => { if (props.active) void refresh() }, [props.active, refresh])
  useEffect(() => onKnowledgeProgress((event) => {
    if (event.jobId !== jobId.current) return
    setStatus(event.message)
    setTone('plain')
  }), [])
  useEffect(() => onKnowledgeDone(async (event: KnowledgeJobResult) => {
    if (event.jobId !== jobId.current) return
    setBusy(false)
    setStatus(event.message)
    setTone(event.failed || event.cancelled ? 'alert' : 'calm')
    await refresh()
  }), [refresh])
  useEffect(() => onKnowledgeGradeDone(async (event: GradeJobResult) => {
    if (event.jobId !== jobId.current) return
    setBusy(false)
    setStatus(event.message)
    setTone(event.ok ? 'calm' : 'alert')
    if (event.run && assessment) {
      const updated = await api.knowledgeAssessment(assessment.id)
      setAssessment(updated)
      setRun(updated.runs.find((item) => item.id === event.run?.id) ?? event.run)
      setCandidateName(event.run.candidate_name ?? '')
    }
    await refresh()
  }), [assessment?.id, refresh])
  useEffect(() => onKnowledgeVisionDone((event: KnowledgeVisionResult) => {
    if (event.jobId !== visionJobId.current) return
    setBusy(false)
    setStatus(event.message)
    setTone(event.ok ? 'calm' : event.cancelled ? 'plain' : 'alert')
    if (event.ok && event.text && event.imageId && event.imageId === selectedImage?.id
      && event.assessmentId === assessment?.id) {
      setRecognizedDraft({ imageId: event.imageId, text: event.text })
    }
  }), [assessment?.id, selectedImage?.id])
  useEffect(() => onAssessmentImportDone(async (event: AssessmentImportResult) => {
    if (event.jobId !== assessmentImportJobId.current) return
    setBusy(false)
    setStatus(event.message)
    setTone(event.failed.length ? 'alert' : 'calm')
    const updated = await api.knowledgeAssessment(event.assessmentId).catch(() => null)
    if (updated) {
      setAssessment(updated)
      const currentImage = selectedImage
        ? updated.images.find((image) => image.id === selectedImage.id)
        : null
      const nextImage = currentImage ?? updated.images[0] ?? null
      setSelectedImage(nextImage)
      if (nextImage) {
        setRecognizedDraft(nextImage.transcription
          ? { imageId: nextImage.id, text: nextImage.transcription }
          : null)
        const preview = await api.knowledgeAssessmentImage(event.assessmentId, nextImage.id).catch(() => null)
        setImagePreview(preview ? `data:${preview.mime};base64,${preview.data}` : '')
      }
    }
    await refresh(false)
  }), [refresh, selectedImage?.id])

  const startJob = async (start: () => Promise<{ jobId: string }>, message: string) => {
    if (busy) return
    try {
      const result = await start()
      jobId.current = result.jobId
      setBusy(true)
      setStatus(message)
      setTone('plain')
    } catch (error) {
      setStatus(messageOf(error))
      setTone('alert')
    }
  }

  const addFiles = async () => {
    try {
      const { paths } = await api.pickFiles('添加本地资料', KNOWLEDGE_FILTER)
      if (paths.length) await startJob(() => api.knowledgeImportPaths(paths), `正在导入 ${paths.length} 项资料…`)
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const addFolder = async () => {
    try {
      const { path } = await api.pickFolder('添加资料文件夹')
      if (path) await startJob(() => api.knowledgeImportPaths([path]), '正在导入资料文件夹…')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const importAssessment = async () => {
    try {
      const { paths } = await api.pickFiles('导入测评 Word 文档', ASSESSMENT_FILTER)
      if (!paths.length) return
      const result = await api.knowledgeImportAssessment(paths[0])
      setAssessment(result.assessment)
      setRun(null)
      setCandidateName('')
      setSelectedImage(null)
      setRecognizedDraft(null)
      setTab('assessment')
      await refresh(false)
      if (result.jobId) {
        assessmentImportJobId.current = result.jobId
        jobId.current = result.jobId
        setBusy(true)
        setStatus(`已导入 ${result.assessment.questions.length} 道题，正在自动识别并关联 ${result.assessment.image_count} 张图片…`)
        setTone('plain')
      } else {
        setStatus(result.visionSkipped
          ? `已导入 ${result.assessment.questions.length} 道题和 ${result.assessment.image_count} 张图片；尚未配置模型服务，图片待识别。`
          : `已导入 ${result.assessment.questions.length} 道题，请检查题干和评分标准。`)
        setTone(result.visionSkipped ? 'alert' : 'calm')
      }
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const openAssessment = async (id: string) => {
    try {
      const result = await api.knowledgeAssessment(id)
      setAssessment(result)
      setRun(null)
      setCandidateName('')
      setSelectedImage(null)
      setRecognizedDraft(null)
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const saveTemplate = async () => {
    if (!assessment) return
    try {
      const result = await api.knowledgeSaveAssessment(assessment.id, assessment.title, assessment.questions)
      setAssessment(result)
      await refresh(false)
      setStatus('测评模板已保存。')
      setTone('calm')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const openImage = async (image: AssessmentImage) => {
    if (!assessment) return
    setSelectedImage(image)
    setRecognizedDraft(null)
    try {
      const result = await api.knowledgeAssessmentImage(assessment.id, image.id)
      setImagePreview(`data:${result.mime};base64,${result.data}`)
    } catch (error) { setImagePreview(''); setStatus(messageOf(error)); setTone('alert') }
  }
  const recognizeImage = async (image: AssessmentImage) => {
    if (!assessment || busy) return
    try {
      const result = await api.knowledgeRecognizeImage(assessment.id, image.id)
      visionJobId.current = result.jobId
      jobId.current = result.jobId
      setBusy(true)
      setStatus('正在将图片发送给当前配置的模型识别…')
      setTone('plain')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const exportImage = async (image: AssessmentImage) => {
    if (!assessment) return
    try {
      const result = await api.knowledgeSaveAssessmentImage(assessment.id, image.id)
      if (result.file) {
        setStatus(`图片已导出：${result.file}`)
        setTone('calm')
      }
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const saveImage = async (transcription: string, questionId: string, role: AssessmentImage['role']) => {
    if (!assessment || !selectedImage) return
    try {
      const image = await api.knowledgeSaveImageTranscription(assessment.id, selectedImage.id, questionId, transcription, role)
      setSelectedImage(image)
      const updated = await api.knowledgeAssessment(assessment.id)
      setAssessment(updated)
      setStatus('图片转录已保存。')
      setTone('calm')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const grade = async () => {
    if (!assessment || busy) return
    try {
      const saved = await api.knowledgeSaveAssessment(assessment.id, assessment.title, assessment.questions)
      setAssessment(saved)
    } catch (error) {
      setStatus(messageOf(error))
      setTone('alert')
      return
    }
    const answers: Record<string, string> = {}
    assessment.questions.forEach((question) => { answers[question.id] = question.answer || '' })
    await startJob(() => api.knowledgeGrade(assessment.id, answers, candidateName.trim()), '正在按评分标准逐题评分…')
  }
  const saveReview = async () => {
    if (!run) return
    try {
      const result = await api.knowledgeUpdateRun(run.id, run.results)
      setRun(result)
      await refresh()
      setStatus('复核结果已保存。')
      setTone('calm')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const exportRun = async () => {
    if (!run) return
    try {
      const { markdown } = await api.knowledgeExportRun(run.id)
      const result = await api.writeTextFile('测评报告.md', markdown)
      if (result.cancelled || !result.file) return
      setStatus('报告已导出。')
      setTone('calm')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const deleteRun = async (id: string) => {
    if (!assessment || !window.confirm('删除这次测评记录？')) return
    try {
      await api.knowledgeDeleteRun(id)
      const deletedCurrent = run?.id === id
      setRun((current) => current?.id === id ? null : current)
      const updated = await api.knowledgeAssessment(assessment.id)
      setAssessment(updated)
      if (deletedCurrent) setCandidateName('')
      setStatus('测评记录已删除。')
      setTone('calm')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const deleteAssessment = async (id: string) => {
    if (!window.confirm('删除此测评模板及其全部测评记录？')) return
    try {
      await api.knowledgeDeleteAssessment(id)
      setAssessment(null)
      setRun(null)
      setCandidateName('')
      setSelectedImage(null)
      await refresh()
      setStatus('测评模板已删除。')
      setTone('calm')
    } catch (error) { setStatus(messageOf(error)); setTone('alert') }
  }
  const openRun = (item: AssessmentRun) => { setRun(item); setCandidateName(item.candidate_name ?? ''); setTab('assessment') }

  const filteredDocs = useMemo(() => docs.filter((doc) => doc.name.toLowerCase().includes(search.toLowerCase())), [docs, search])
  const selectedDocument = docs.find((doc) => doc.doc_id === selectedDoc) ?? null

  return (
    <div className="page knowledge-page">
      <header className="page-head">
        <div className="page-head-main">
          <div className="eyebrow settings-eyebrow">LOCAL KNOWLEDGE　/　本地资料与测评</div>
          <h1 className="page-title">本地知识库</h1>
          <p className="page-sub">资料保存在本机；可检索原文，也可把 Word 测评表整理成可复核的评分流程。</p>
        </div>
        <div className="page-head-side"><Pill tone="plain"><Icon name="database" size={12} />{docs.length} 份资料</Pill></div>
      </header>

      <div className="knowledge-layout">
        <aside className="knowledge-sidebar">
          <div className="knowledge-tabs" role="tablist" aria-label="知识库功能">
            <button role="tab" aria-selected={tab === 'library'} onClick={() => setTab('library')}><Icon name="book" size={15} />资料库</button>
            <button role="tab" aria-selected={tab === 'assessment'} onClick={() => setTab('assessment')}><Icon name="check-circle" size={15} />业务测评</button>
          </div>
          {tab === 'library' ? (
            <>
              <div className="knowledge-side-head"><strong>资料</strong><button className="icon-btn" title="刷新资料" onClick={() => void refresh()}><Icon name="refresh" size={14} /></button></div>
              <label className="knowledge-search"><Icon name="search" size={14} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="查找资料名称" /></label>
              <div className="knowledge-doc-list">
                {filteredDocs.map((doc) => <button key={doc.doc_id} className={`knowledge-doc-item${selectedDoc === doc.doc_id ? ' is-selected' : ''}`} onClick={() => setSelectedDoc(doc.doc_id)}>
                  <Icon name="file" size={15} /><span><strong>{doc.name}</strong><small>{doc.page_count ?? 0} 段索引{doc.wiki_error ? ' · Wiki 未生成' : ''}</small></span>
                </button>)}
                {!filteredDocs.length && <div className="knowledge-empty-small">{docs.length ? '没有匹配的资料' : '添加资料后即可检索'}</div>}
              </div>
              <div className="knowledge-sidebar-actions">
                <Button small onClick={() => void addFiles()} disabled={busy}><Icon name="plus" size={13} />添加文件</Button>
                <Button small onClick={() => void addFolder()} disabled={busy}><Icon name="folder" size={13} />添加文件夹</Button>
                <Button small onClick={() => void importAssessment()} disabled={busy}><Icon name="check-circle" size={13} />导入测评 Word</Button>
              </div>
            </>
          ) : (
            <>
              <div className="knowledge-side-head"><strong>测评模板</strong><button className="icon-btn" title="导入 Word" onClick={() => void importAssessment()} disabled={busy}><Icon name="plus" size={14} /></button></div>
              <div className="knowledge-doc-list">
                {assessments.map((item) => <button key={item.id} className={`knowledge-doc-item${assessment?.id === item.id ? ' is-selected' : ''}`} onClick={() => void openAssessment(item.id)}>
                  <Icon name="clipboard" size={15} /><span><strong>{item.title}</strong><small>{item.question_count ?? 0} 道题 · {item.run_count ?? 0} 次测评</small></span>
                </button>)}
                {!assessments.length && <div className="knowledge-empty-small">导入 Word 测评文档开始</div>}
              </div>
              {assessment?.runs?.length ? <div className="knowledge-run-list"><div className="knowledge-side-head"><strong>最近测评</strong></div>
                {assessment.runs.map((item) => <div key={item.id} className="knowledge-run-item"><button onClick={() => openRun(item)}><span>{new Date(item.created_at).toLocaleDateString()}</span><b>{item.score}/{item.max_score}</b><small>{item.status === 'reviewed' ? '已复核' : '待复核'}</small></button><button className="knowledge-run-delete" title="删除记录" onClick={() => void deleteRun(item.id)}><Icon name="trash" size={12} /></button></div>)}
              </div> : null}
            </>
          )}
          <div className="knowledge-privacy"><Icon name="info" size={14} /><span>检索在本机完成。测评评分会将当前题目、评分标准和答案发送给偏好设置中的模型。</span></div>
        </aside>

        <main className="knowledge-main">
          {busy && status && <ProcessingBanner text={status} />}
          {tab === 'library' ? <LibraryView
            docs={docs} selectedDoc={selectedDocument}
            onSelect={(doc) => setSelectedDoc(doc.doc_id)}
            enabled={props.settings.knowledge_enabled ?? true} busy={busy} status={status} tone={tone}
            onEnabled={(knowledge_enabled) => props.onSettings({ knowledge_enabled })}
            onAddFiles={() => void addFiles()} onAddFolder={() => void addFolder()}
            onRebuild={() => { if (selectedDocument) void startJob(() => api.knowledgeRebuild(String(selectedDocument.doc_id)), `正在重建 ${selectedDocument.name}…`) }}
            onRemove={() => { if (selectedDocument && window.confirm(`移除“${selectedDocument.name}”？`)) void api.knowledgeRemove(String(selectedDocument.doc_id)).then(() => { setSelectedDoc(null); return refresh() }).catch((error) => { setStatus(messageOf(error)); setTone('alert') }) }}
            onClear={() => { if (docs.length && window.confirm('确定清空全部资料与索引？')) void api.knowledgeClear().then(() => { setSelectedDoc(null); return refresh() }).catch((error) => { setStatus(messageOf(error)); setTone('alert') }) }}
            onSearch={async (query) => { try { const result = await api.knowledgeSearch(query); setStatus(result.hits.length ? `找到 ${result.hits.length} 段相关资料。` : '没有找到相关片段。'); setTone(result.hits.length ? 'calm' : 'plain'); setSearchQuery(query); setSearchHits(result.hits) } catch (error) { setStatus(messageOf(error)); setTone('alert') } }}
            search={search} setSearch={setSearch} searchHits={searchHits} searchQuery={searchQuery}
          /> : <AssessmentView
            assessment={assessment} run={run} busy={busy} settingsReady={Boolean(props.settings.base_url && props.settings.model)}
            selectedImage={selectedImage} imagePreview={imagePreview} status={status} tone={tone}
            recognizedDraft={recognizedDraft}
            onImport={() => void importAssessment()} onQuestionChange={(id, patch) => setAssessment((current) => current ? ({ ...current, questions: current.questions.map((item) => item.id === id ? { ...item, ...patch } : item) }) : current)}
            onTitleChange={(title) => setAssessment((current) => current ? { ...current, title } : current)}
            onSaveTemplate={() => void saveTemplate()} onGrade={() => void grade()}
            onImageSelect={(image) => void openImage(image)} onImageSave={(text, questionId, role) => void saveImage(text, questionId, role)}
            onImageExport={(image) => void exportImage(image)}
            onImageRecognize={(image) => void recognizeImage(image)}
            onRunChange={(next) => setRun(next)} onSaveReview={() => void saveReview()} onExport={() => void exportRun()}
            onCancel={() => { if (busy) void api.cancelJob(jobId.current) }}
            onDeleteAssessment={deleteAssessment} onDeleteRun={deleteRun}
            candidateName={candidateName} onCandidateName={setCandidateName}
          />}
          {status && !busy && <StatusLine text={status} tone={tone} />}
        </main>
      </div>
    </div>
  )
}

function ProcessingBanner(props: { text: string }) {
  const match = props.text.match(/\((\d+)\s*\/\s*(\d+)\)/)
  const current = match ? Number(match[1]) : 0
  const total = match ? Number(match[2]) : 0
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0
  return (
    <div className="knowledge-processing" role="status" aria-live="polite">
      <i aria-hidden />
      <div>
        <strong>文档正在处理</strong>
        <p>{props.text}</p>
        {total > 0 && (
          <div className="knowledge-processing-track" aria-hidden>
            <span style={{ width: `${percent}%` }} />
          </div>
        )}
      </div>
    </div>
  )
}

function LibraryView(props: {
  docs: KnowledgeDoc[]
  selectedDoc: KnowledgeDoc | null
  onSelect: (doc: KnowledgeDoc) => void
  enabled: boolean
  busy: boolean
  status: string
  tone: 'plain' | 'calm' | 'alert'
  onEnabled: (value: boolean) => void
  onAddFiles: () => void
  onAddFolder: () => void
  onRebuild: () => void
  onRemove: () => void
  onClear: () => void
  onSearch: (query: string) => void
  search: string
  setSearch: (value: string) => void
  searchHits: KnowledgeHit[]
  searchQuery: string
}) {
  const [query, setQuery] = useState('')
  return (
    <div className="knowledge-view">
      <section className="knowledge-welcome">
        <div className="knowledge-welcome-mark"><Icon name="book" size={20} /></div>
        <div><h2>让资料成为可查的依据</h2><p>支持 Word、PDF、Excel 与文本。原文切块并建立本地全文索引，问答时只检索相关片段。</p></div>
        <div className="knowledge-welcome-actions"><Button primary onClick={props.onAddFiles} disabled={props.busy}><Icon name="plus" size={14} />添加文件</Button><Button onClick={props.onAddFolder} disabled={props.busy}><Icon name="folder" size={14} />添加文件夹</Button></div>
      </section>
      <div className="knowledge-metrics">
        <div><span>资料</span><strong>{props.docs.length}</strong><small>份已导入</small></div>
        <div><span>索引段落</span><strong>{props.docs.reduce((sum, doc) => sum + (doc.page_count ?? 0), 0)}</strong><small>可供全文检索</small></div>
        <div className="knowledge-toggle-metric"><span>对话检索</span><Toggle label="回答时查阅本地资料" checked={props.enabled} disabled={!props.docs.length && !props.enabled} onChange={props.onEnabled} /></div>
      </div>
      <section className="knowledge-section">
        <div className="knowledge-section-head"><div><h2>资料清单</h2><p>单文件不超过 30 MB；图片文字会标记为未识别，不纳入文本检索。</p></div><div className="knowledge-section-actions"><Button small onClick={props.onRebuild} disabled={props.busy || !props.selectedDoc}>重建所选</Button><Button small onClick={props.onRemove} disabled={props.busy || !props.selectedDoc}>移除所选</Button><Button small danger onClick={props.onClear} disabled={props.busy || !props.docs.length}>清空</Button></div></div>
        {props.docs.length ? <div className="knowledge-table"><div className="knowledge-table-head"><span>资料名称</span><span>索引段落</span><span>导入时间</span><span>状态</span></div>
          {props.docs.map((doc) => <button key={doc.doc_id} className={`knowledge-table-row${props.selectedDoc?.doc_id === doc.doc_id ? ' is-selected' : ''}`} onClick={() => props.onSelect(doc)}>
            <span className="knowledge-file-name"><Icon name="file" size={15} /><span><strong>{doc.name}</strong><small>{doc.source_path}</small></span></span><span>{doc.page_count ?? 0}</span><span>{doc.added_at ? new Date(doc.added_at).toLocaleDateString() : '—'}</span><span><Pill tone={doc.wiki_error ? 'caution' : 'calm'}>{doc.wiki_error ? '原文可查' : '已索引'}</Pill></span>
          </button>)}
        </div> : <div className="knowledge-empty"><Icon name="database" size={28} /><strong>资料库还是空的</strong><span>从 Word、PDF、表格或文本开始添加。原文件和索引保存在本机。</span><Button onClick={props.onAddFiles}>选择资料</Button></div>}
      </section>
      <section className="knowledge-section knowledge-search-section">
        <div className="knowledge-section-head"><div><h2>检索预览</h2><p>查看本地全文检索会为一个问题找到哪些片段。</p></div></div>
        <form className="knowledge-query" onSubmit={(event) => { event.preventDefault(); if (query.trim()) props.onSearch(query.trim()) }}><Icon name="search" size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入关键词或问题" /><Button primary disabled={!query.trim()}>搜索资料</Button></form>
        {props.searchHits.length > 0 && <div className="knowledge-hit-list">{props.searchHits.map((hit, index) => <article key={`${hit.doc_id}-${hit.title}-${index}`}><div><Pill tone="line">{hit.kind === 'wiki' ? 'Wiki' : '原文'}</Pill><strong>{hit.doc_name}</strong></div><p><HighlightedText text={hit.text ?? ''} query={props.searchQuery} /></p></article>)}</div>}
      </section>
      <div className="knowledge-note"><Icon name="info" size={15} /><span>全文检索在本机运行。启用对话检索时，命中的少量资料片段会发送给当前配置的模型；导入原文不会自动上传。</span></div>
    </div>
  )
}

function AssessmentView(props: {
  assessment: Assessment | null
  run: AssessmentRun | null
  busy: boolean
  settingsReady: boolean
  selectedImage: AssessmentImage | null
  imagePreview: string
  recognizedDraft: { imageId: string; text: string } | null
  status: string
  tone: 'plain' | 'calm' | 'alert'
  onImport: () => void
  onTitleChange: (title: string) => void
  onQuestionChange: (id: string, patch: Partial<AssessmentQuestion>) => void
  onSaveTemplate: () => void
  onGrade: () => void
  onImageSelect: (image: AssessmentImage) => void
  onImageSave: (text: string, questionId: string, role: AssessmentImage['role']) => void
  onImageExport: (image: AssessmentImage) => void
  onImageRecognize: (image: AssessmentImage) => void
  onRunChange: (run: AssessmentRun) => void
  onSaveReview: () => void
  onExport: () => void
  onCancel: () => void
  onDeleteAssessment: (id: string) => void
  onDeleteRun: (id: string) => void
  candidateName: string
  onCandidateName: (name: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [transcription, setTranscription] = useState('')
  const [imageQuestion, setImageQuestion] = useState('')
  const [imageRole, setImageRole] = useState<AssessmentImage['role']>('unclassified')
  useEffect(() => {
    setTranscription(props.selectedImage?.transcription ?? '')
    setImageQuestion(props.selectedImage?.question_id ?? '')
    setImageRole(props.selectedImage?.role ?? 'unclassified')
  }, [props.selectedImage?.id])
  useEffect(() => {
    if (props.selectedImage && props.recognizedDraft?.imageId === props.selectedImage.id) {
      setTranscription(props.recognizedDraft.text)
    }
  }, [props.recognizedDraft?.imageId, props.recognizedDraft?.text, props.selectedImage?.id])
  if (!props.assessment) return <div className="assessment-empty"><div className="knowledge-welcome-mark"><Icon name="check-circle" size={20} /></div><h2>从测评 Word 开始</h2><p>系统会把编号题目整理为草稿。导入后请核对题干、评分点和满分，再开始逐题测评。</p><Button primary onClick={props.onImport}><Icon name="plus" size={14} />导入测评文档</Button></div>
  const resultMap = new Map((props.run?.results ?? []).map((result) => [result.question_id, result]))
  const reviewed = props.run?.status === 'reviewed'
  return (
    <div className="assessment-view">
      <div className="assessment-titlebar"><div><div className="eyebrow settings-eyebrow">ASSESSMENT　/　评分模板</div><input className="assessment-title-input" value={props.assessment.title} disabled={Boolean(props.run)} onChange={(event) => props.onTitleChange(event.target.value)} aria-label="测评名称" /><p>来源：{props.assessment.source_name} · {props.assessment.questions.length} 道题 · {props.assessment.image_count} 张图片 · 分值合计 {props.assessment.questions.reduce((sum, item) => sum + item.max_score, 0)} 分</p></div><div className="knowledge-section-actions"><Pill tone={reviewed ? 'calm' : 'caution'}>{reviewed ? '已人工复核' : '评分需复核'}</Pill><Button small onClick={props.onSaveTemplate} disabled={Boolean(props.run)}>保存模板</Button><Button small danger onClick={() => props.onDeleteAssessment(props.assessment!.id)}>删除模板</Button></div></div>
      {props.assessment.declared_score > 0 && Math.abs(props.assessment.questions.reduce((sum, item) => sum + item.max_score, 0) - props.assessment.declared_score) > 0.01 && <div className="assessment-warning"><Icon name="info" size={14} />题目分值合计 {props.assessment.questions.reduce((sum, item) => sum + item.max_score, 0)} 分，文档标注满分 {props.assessment.declared_score} 分；请核对后再使用总分。</div>}
      {props.assessment.overview && <details className="assessment-overview"><summary>文档说明与总分结构</summary><pre>{props.assessment.overview}</pre></details>}
      {props.assessment.image_count > 0 && <section className="assessment-images"><div><strong><Icon name="image" size={15} />内嵌图片与手写答案</strong><span>已自动识别的文字先作为草稿保存；你可以修改图片用途、题目关联和转录内容。</span></div><div className="assessment-image-list">{props.assessment.images.map((image) => <button key={image.id} className={props.selectedImage?.id === image.id ? 'is-selected' : ''} onClick={() => props.onImageSelect(image)}><Icon name="image" size={14} />{image.name}<small>{image.transcription ? '已识别' : props.busy ? '识别中' : '待识别'} · {image.role === 'reference' ? '评分参考' : image.role === 'answer' ? '受测人作答' : '待分类'}</small></button>)}</div>
        {props.selectedImage && <div className="assessment-image-editor">{props.imagePreview && <img src={props.imagePreview} alt={props.selectedImage.name} />}<label>图片用途<select value={imageRole} onChange={(event) => setImageRole(event.target.value as AssessmentImage['role'])}><option value="unclassified">待分类 / 仅保留</option><option value="reference">评分参考答案</option><option value="answer">受测人作答</option></select></label><label>关联题目<select value={imageQuestion} onChange={(event) => setImageQuestion(event.target.value)}><option value="">不关联题目</option>{props.assessment.questions.map((q) => <option key={q.id} value={q.id}>第 {q.number} 题</option>)}</select></label><label>图片文字转录<textarea value={transcription} onChange={(event) => setTranscription(event.target.value)} placeholder="运行模型识别后可在这里校对，也可手动录入" /></label><Button small onClick={() => props.onImageRecognize(props.selectedImage!)} disabled={props.busy || !props.settingsReady}><Icon name="sparkles" size={13} />{props.busy ? '正在识别…' : '模型识别文字'}</Button><Button small primary onClick={() => props.onImageSave(transcription, imageQuestion, imageRole)} disabled={props.busy}>保存转录</Button><Button small onClick={() => props.onImageExport(props.selectedImage!)}>导出图片</Button><small className="assessment-vision-note">图片会发送到偏好设置中配置的模型服务。模型需支持图片输入；识别文本仅作为草稿，确认后才会保存或用于评分。</small></div>}
      </section>}
      <div className="assessment-toolbar"><div><strong>逐题作答</strong><span>模型只提供初评；保存复核后才标记为已审核。</span></div><div className="knowledge-section-actions"><Button small onClick={() => setEditing((value) => !value)} disabled={Boolean(props.run)}>{editing ? '结束编辑' : '校对题目'}</Button>{props.busy ? <Button small danger onClick={props.onCancel}>取消评分</Button> : <Button small primary onClick={props.onGrade} disabled={!props.settingsReady || Boolean(props.run)}>生成评分建议</Button>}</div></div>
      {!props.run && <label className="assessment-candidate">受测人<input value={props.candidateName} onChange={(event) => props.onCandidateName(event.target.value)} placeholder="姓名或工号（可选）" /></label>}
      {!props.settingsReady && <div className="assessment-warning"><Icon name="info" size={14} />评分需要在偏好设置配置模型。题目、评分标准和答案会发送到该模型服务。</div>}
      {props.assessment.questions.map((question) => {
        const result = resultMap.get(question.id)
        return <article key={question.id} className="assessment-question"><div className="assessment-question-head"><div><Pill tone="line">{question.category || '未分类'}</Pill><h3>第 {question.number} 题</h3></div><label>满分 <input type="number" min="1" max="100" value={question.max_score} disabled={!editing} onChange={(event) => props.onQuestionChange(question.id, { max_score: Number(event.target.value) })} /></label></div>
          {editing ? <textarea className="assessment-edit-prompt" value={question.prompt} onChange={(event) => props.onQuestionChange(question.id, { prompt: event.target.value })} /> : <p className="assessment-question-prompt">{question.prompt}</p>}
          <div className="assessment-two-col"><label><span>题目补充 / 评分标准</span><textarea disabled={!editing} value={question.guide} onChange={(event) => props.onQuestionChange(question.id, { guide: event.target.value })} placeholder="导入时自动归入此题，可在校对模式修订" /></label><label><span>参考答案</span><textarea disabled={!editing} value={question.reference} onChange={(event) => props.onQuestionChange(question.id, { reference: event.target.value })} placeholder="可补充标准答案；模型不会自行把猜测当标准" /></label></div>
          {!props.run ? <label className="assessment-answer"><span>考生答案</span><textarea value={question.answer} onChange={(event) => props.onQuestionChange(question.id, { answer: event.target.value })} placeholder="录入或粘贴该题答案" /></label> : <div className="assessment-answer-read"><span>考生答案</span><p>{props.run.answers[question.id] || '未作答'}</p></div>}
          {result && <div className="assessment-result"><div className="assessment-score"><b>{result.score}</b><span>/ {result.max_score} 分</span><label>复核得分<input type="number" min="0" max={result.max_score} step="0.5" disabled={reviewed} value={result.score} onChange={(event) => props.onRunChange({ ...props.run!, results: props.run!.results.map((item) => item.question_id === question.id ? { ...item, score: Number(event.target.value) } : item) })} /></label></div><div className="assessment-feedback"><strong>评分说明</strong><p>{result.feedback}</p><strong>评分依据</strong><p>{result.evidence}</p>{result.criteria.length > 0 && <ul>{result.criteria.map((criterion, index) => <li key={index} className={criterion.met ? 'met' : 'missed'}><Icon name={criterion.met ? 'check' : 'x'} size={12} /><span>{criterion.item}：{criterion.reason}</span></li>)}</ul>}</div></div>}
        </article>
      })}
      {props.run && <div className="assessment-report-bar"><div><span>{reviewed ? '复核总分' : '建议总分'}</span><strong>{props.run.results.reduce((sum, item) => sum + item.score, 0)} / {props.run.results.reduce((sum, item) => sum + item.max_score, 0)}{props.assessment.declared_score > 0 && props.assessment.declared_score !== props.run.results.reduce((sum, item) => sum + item.max_score, 0) ? `（文档标注 ${props.assessment.declared_score}）` : ''}</strong></div><div className="knowledge-section-actions">{!reviewed && <Button primary onClick={props.onSaveReview}>保存人工复核</Button>}<Button onClick={props.onExport}><Icon name="download" size={13} />导出报告</Button><Button danger onClick={() => props.onDeleteRun(props.run!.id)}>删除本次记录</Button></div></div>}
    </div>
  )
}
