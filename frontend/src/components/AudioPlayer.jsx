import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { audioUrl } from '../api'

function fmtTime(s) {
  if (!isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

const AudioPlayer = forwardRef(function AudioPlayer({ meetingId, onTimeUpdate }, ref) {
  const audioRef = useRef(null)
  const barRef   = useRef(null)
  const durRef   = useRef(0)          // 始终保存最新 duration，供 document 事件读取

  const [playing,  setPlaying]  = useState(false)
  const [current,  setCurrent]  = useState(0)
  const [duration, setDuration] = useState(0)
  const [dragging, setDragging] = useState(false)

  useImperativeHandle(ref, () => ({
    seek(time) {
      if (!audioRef.current) return
      audioRef.current.currentTime = time
      setCurrent(time)
    },
  }))

  // 用 document 级别的 mousemove / mouseup 捕获拖动，鼠标移出进度条也有效
  useEffect(() => {
    if (!dragging) return

    const onMove = (e) => {
      const rect = barRef.current?.getBoundingClientRect()
      if (!rect || !durRef.current) return
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      const time = ratio * durRef.current
      setCurrent(time)
      if (audioRef.current) audioRef.current.currentTime = time
    }
    const onUp = () => setDragging(false)

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }
  }, [dragging])

  const handleBarClick = (e) => {
    const rect = barRef.current?.getBoundingClientRect()
    if (!rect || !durRef.current) return
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const time = ratio * durRef.current
    if (audioRef.current) audioRef.current.currentTime = time
    setCurrent(time)
  }

  const pct = duration ? (current / duration) * 100 : 0

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 mb-5 shadow-sm">
      <audio
        ref={audioRef}
        src={audioUrl(meetingId)}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => {
          if (dragging) return          // 拖动期间忽略 audio 自身的 timeupdate
          const t = e.target.currentTime
          setCurrent(t)
          onTimeUpdate?.(t)
        }}
        onLoadedMetadata={(e) => {
          setDuration(e.target.duration)
          durRef.current = e.target.duration
        }}
      />

      <div className="flex items-center gap-3">
        {/* Play/Pause */}
        <button
          onClick={() => playing ? audioRef.current?.pause() : audioRef.current?.play()}
          className="w-9 h-9 flex-shrink-0 bg-blue-600 hover:bg-blue-700 rounded-full flex items-center justify-center text-white transition-colors shadow-sm"
        >
          {playing ? (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
              <rect x="2" y="1" width="4" height="12" rx="1" />
              <rect x="8" y="1" width="4" height="12" rx="1" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
              <path d="M3 1.5l9 5.5-9 5.5V1.5z" />
            </svg>
          )}
        </button>

        <span className="text-xs text-gray-500 w-10 flex-shrink-0 text-right font-mono">
          {fmtTime(current)}
        </span>

        {/* Progress bar */}
        <div
          ref={barRef}
          className="flex-1 h-1.5 bg-gray-200 rounded-full cursor-pointer relative group select-none"
          onClick={handleBarClick}
          onMouseDown={() => setDragging(true)}
        >
          <div
            className="h-1.5 bg-blue-500 rounded-full relative pointer-events-none"
            style={{ width: `${pct}%` }}
          >
            <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-600 rounded-full shadow opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>

        <span className="text-xs text-gray-400 w-10 flex-shrink-0 font-mono">
          {fmtTime(duration)}
        </span>
      </div>
    </div>
  )
})

export default AudioPlayer
