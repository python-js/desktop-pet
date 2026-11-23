// Minimal Markdown renderer for assistant replies: headings, lists, quotes,
// fenced code, inline emphasis/links, and local knowledge-base figures.
import { ReactNode, useEffect, useState } from 'react'
import { api } from '../api'

const INLINE = /(\[\[img:[0-9a-f]{16,64}\]\]|\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*|\[[^\]\n]+\]\([^)\s]+\))/g
const IMAGE_LINE = /^\[\[img:([0-9a-f]{16,64})\]\]\s*$/

function DocImage(props: { id: string }) {
  const [src, setSrc] = useState('')
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let alive = true
    api.knowledgeImage(props.id).then((result) => {
      if (alive) setSrc(`data:${result.mime};base64,${result.data}`)
    }).catch(() => {})
    return () => { alive = false }
  }, [props.id])
  if (!src) return null
  return (
    <>
      <button type="button" className="md-figure" onClick={() => setOpen(true)}>
        <img src={src} alt="" />
      </button>
      {open && (
        <button type="button" className="md-figure-zoom" onClick={() => setOpen(false)}>
          <img src={src} alt="" />
        </button>
      )}
    </>
  )
}

function safeHref(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null
}

export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0
    if (index > last) out.push(text.slice(last, index))
    const token = match[0]
    const key = `${index}-${token.length}`
    if (token.startsWith('[[img:')) {
      out.push(<DocImage key={key} id={token.slice(6, -2)} />)
    } else if (token.startsWith('**')) {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      out.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('*')) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>)
    } else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token)
      const href = link ? safeHref(link[2]) : null
      out.push(
        href && link ? (
          <a key={key} href={href} target="_blank" rel="noreferrer">{link[1]}</a>
        ) : (
          <span key={key}>{link ? link[1] : token}</span>
        ),
      )
    }
    last = index + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const SPECIAL = /^(```|#{1,3}\s|>\s?|\s*[-*+]\s+|\s*\d+\.\s+|-{3,}\s*$|\*{3,}\s*$|\[\[img:[0-9a-f]{16,64}\]\]\s*$)/

export default function Markdown(props: { text: string }) {
  const lines = props.text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <pre key={key++}>
          {lang && <span className="md-lang">{lang}</span>}
          <code>{body.join('\n')}</code>
        </pre>,
      )
      continue
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      const Tag = `h${heading[1].length}` as 'h1' | 'h2' | 'h3'
      blocks.push(<Tag key={key++}>{inline(heading[2])}</Tag>)
      index += 1
      continue
    }
    const figure = IMAGE_LINE.exec(line.trim())
    if (figure) {
      blocks.push(<DocImage key={key++} id={figure[1]} />)
      index += 1
      continue
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push(<hr key={key++} />)
      index += 1
      continue
    }
    if (/^\s*>\s?/.test(line)) {
      const body: string[] = []
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        body.push(lines[index].replace(/^\s*>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={key++}>
          {body.map((row, rowIndex) => <p key={rowIndex}>{inline(row)}</p>)}
        </blockquote>,
      )
      continue
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={key++}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}
        </ul>,
      )
      continue
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(
        <ol key={key++}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}
        </ol>,
      )
      continue
    }
    const paragraph: string[] = [line]
    index += 1
    while (index < lines.length && lines[index].trim() && !SPECIAL.test(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(
      <p key={key++}>{inline(paragraph.join('\n'))}</p>,
    )
  }

  return <div className="md">{blocks}</div>
}
