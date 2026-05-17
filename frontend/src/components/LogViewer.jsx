import { useEffect, useRef, useState } from 'react'
import { getMeetingLogs } from '../api'

export default function LogViewer({ meetingId, isProcessing }) {
  const [lines, setLines] = useState([])
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef(null)
  const containerRef = useRef(null)

  useEffect(() => {
    const load = async () => {
      try {
        const r = await getMeetingLogs(meetingId)
        setLines(r.data.lines || [])
      } catch {}
    }
    load()
    if (!isProcessing) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [meetingId, isProcessing])

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  const colorLine = (line) => {
    if (line.includes('[错误]') || line.includes('Error') || line.includes('Traceback'))
      return 'text-red-600'
    if (line.includes('[进度]') || line.includes('完成'))
      return 'text-emerald-600'
    if (line.includes('加载') || line.includes('下载') || line.includes('Downloading') || line.includes('↓'))
      return 'text-blue-600'
    if (line.includes('警告') || line.includes('Warning') || line.includes('skipped'))
      return 'text-amber-600'
    return 'text-gray-600'
  }

  return (
    <div className="relative">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="bg-gray-50 border border-gray-200 rounded-xl p-4 h-96 overflow-y-auto font-mono text-xs leading-relaxed"
      >
        {lines.length === 0 ? (
          <p className="text-gray-400 italic">
            {isProcessing ? '等待日志输出...' : '暂无日志'}
          </p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={colorLine(line)}>
              {line || ' '}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {!autoScroll && isProcessing && (
        <button
          onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }}
          className="absolute bottom-3 right-3 bg-white hover:bg-gray-50 text-gray-600 text-xs px-2 py-1 rounded-lg border border-gray-300 shadow-sm transition-colors"
        >
          ↓ 跳到最新
        </button>
      )}
    </div>
  )
}
