import { useEffect, useRef, useState } from 'react'
import { exportMeeting } from '../api'

function downloadText(content, filename) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const SUBTITLE_LANGS = [
  { key: 'original',  label: '原文字幕',   hint: '识别出来的原始语言' },
  { key: 'zh',        label: '中文字幕',   hint: '译文，未翻译的片段回退原文' },
  { key: 'bilingual', label: '双语字幕',   hint: '中文在上、原文在下' },
]

export default function ExportPanel({ meetingId, hasTranslation, hasSpeakers = true }) {
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState('')
  const [menu, setMenu] = useState(false)
  const [withSpeaker, setWithSpeaker] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    if (!menu) return
    const onClick = (e) => {
      if (!wrapRef.current?.contains(e.target)) setMenu(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [menu])

  const handleExport = async (format, lang = 'original') => {
    const key = `${format}:${lang}`
    setLoading(key)
    try {
      const r = await exportMeeting(meetingId, format, lang, withSpeaker)
      const { content, title, filename } = r.data
      downloadText(content, filename || `${title}.${format}`)
      setMenu(false)
    } finally {
      setLoading('')
    }
  }

  const handleCopy = async () => {
    const r = await exportMeeting(meetingId, 'text', hasTranslation ? 'bilingual' : 'original')
    await navigator.clipboard.writeText(r.data.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const btn = 'px-3 py-1.5 text-xs rounded-lg border transition-colors font-medium'
  const plain = 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400'

  return (
    <div className="flex items-center gap-1.5">
      {/* 字幕导出下拉 */}
      <div className="relative" ref={wrapRef}>
        <button
          className={`${btn} ${menu ? 'bg-blue-50 border-blue-300 text-blue-700' : plain}`}
          onClick={() => setMenu((v) => !v)}
        >
          字幕 ▾
        </button>

        {menu && (
          <div className="absolute right-0 mt-1.5 w-64 bg-white rounded-xl border border-gray-200 shadow-lg z-30 p-2">
            {!hasTranslation && (
              <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-2.5 py-1.5 mb-1.5">
                尚未翻译，中文/双语字幕会退回原文
              </p>
            )}
            {SUBTITLE_LANGS.map((l) => (
              <div key={l.key} className="px-2.5 py-1.5 rounded-lg hover:bg-slate-50">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-700">{l.label}</p>
                    <p className="text-[11px] text-gray-400 truncate">{l.hint}</p>
                  </div>
                  <div className="flex gap-1 flex-shrink-0">
                    {['srt', 'vtt'].map((fmt) => (
                      <button
                        key={fmt}
                        onClick={() => handleExport(fmt, l.key)}
                        disabled={!!loading}
                        className="px-2 py-1 text-[11px] font-medium rounded-md border border-gray-200 text-gray-600 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-colors disabled:opacity-40"
                      >
                        {loading === `${fmt}:${l.key}` ? '...' : fmt.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ))}

            {hasSpeakers && (
              <label className="flex items-center gap-2 px-2.5 pt-2 mt-1 border-t border-gray-100 text-xs text-gray-500 cursor-pointer">
                <input
                  type="checkbox"
                  checked={withSpeaker}
                  onChange={(e) => setWithSpeaker(e.target.checked)}
                  className="w-3.5 h-3.5 accent-blue-600"
                />
                字幕中带说话人名字
              </label>
            )}
          </div>
        )}
      </div>

      <button
        className={`${btn} ${plain}`}
        onClick={() => handleExport('markdown', hasTranslation ? 'bilingual' : 'original')}
        disabled={!!loading}
      >
        {loading.startsWith('markdown') ? '...' : 'Markdown'}
      </button>
      <button
        className={`${btn} ${plain}`}
        onClick={() => handleExport('text', hasTranslation ? 'bilingual' : 'original')}
        disabled={!!loading}
      >
        {loading.startsWith('text') ? '...' : '纯文本'}
      </button>
      <button
        className={`${btn} ${
          copied
            ? 'bg-emerald-50 border-emerald-300 text-emerald-700'
            : plain
        }`}
        onClick={handleCopy}
      >
        {copied ? '已复制' : '复制'}
      </button>
    </div>
  )
}
