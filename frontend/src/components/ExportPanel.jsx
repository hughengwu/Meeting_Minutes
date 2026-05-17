import { useState } from 'react'
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

export default function ExportPanel({ meetingId }) {
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState('')

  const handleExport = async (format) => {
    setLoading(format)
    try {
      const r = await exportMeeting(meetingId, format)
      const { content, title } = r.data
      downloadText(content, `${title}.${format === 'markdown' ? 'md' : 'txt'}`)
    } finally {
      setLoading('')
    }
  }

  const handleCopy = async () => {
    const r = await exportMeeting(meetingId, 'text')
    await navigator.clipboard.writeText(r.data.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const btn = 'px-3 py-1.5 text-xs rounded-lg border transition-colors font-medium'

  return (
    <div className="flex items-center gap-1.5">
      <button
        className={`${btn} bg-white border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400`}
        onClick={() => handleExport('markdown')}
        disabled={!!loading}
      >
        {loading === 'markdown' ? '...' : 'Markdown'}
      </button>
      <button
        className={`${btn} bg-white border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400`}
        onClick={() => handleExport('text')}
        disabled={!!loading}
      >
        {loading === 'text' ? '...' : '纯文本'}
      </button>
      <button
        className={`${btn} ${
          copied
            ? 'bg-emerald-50 border-emerald-300 text-emerald-700'
            : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400'
        }`}
        onClick={handleCopy}
      >
        {copied ? '已复制' : '复制'}
      </button>
    </div>
  )
}
