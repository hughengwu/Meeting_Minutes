import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { audioUrl } from '../api'

function fmtTime(s) {
  if (!isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

const AudioPlayer = forwardRef(function AudioPlayer({ meetingId, onTimeUpdate }, ref) {
  const audioRef   = useRef(null)
  const barRef      = useRef(null)
  const durRef      = useRef(0)      // duration 的 ref 版本，供事件回调同步读取
  const draggingRef = useRef(false)  // 用 ref 而非 state，避免闭包拿到过期值
  const dragTimeRef = useRef(0)      // 拖动期间实时记录目标时间，mouseup 直接用

  const [playing,  setPlaying]  = useState(false)
  const [current,  setCurrent]  = useState(0)
  const [duration, setDuration] = useState(0)

  useImperativeHandle(ref, () => ({
    seek(time) {
      if (!audioRef.current) return
      audioRef.current.currentTime = time
      setCurrent(time)
    },
  }))

  const timeFromX = (clientX) => {
    const rect = barRef.current?.getBoundingClientRect()
    if (!rect || !durRef.current) return null
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) * durRef.current
  }

  const handleBarMouseDown = (e) => {
    e.preventDefault()
    draggingRef.current = true

    // 立即更新可视位置
    const t0 = timeFromX(e.clientX)
    if (t0 !== null) { setCurrent(t0); dragTimeRef.current = t0 }

    const onMove = (e) => {
      const t = timeFromX(e.clientX)
      if (t !== null) { setCurrent(t); dragTimeRef.current = t }
    }

    const onUp = () => {
      draggingRef.current = false
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)

      const t = dragTimeRef.current
      if (audioRef.current) {
        audioRef.current.currentTime = t
        setCurrent(t)
        onTimeUpdate?.(t)
      }
    }

    // 挂在 document 上：鼠标移出进度条也能正确响应
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const pct = duration ? (current / duration) * 100 : 0

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <audio
        ref={audioRef}
        src={audioUrl(meetingId)}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => {
          if (draggingRef.current) return   // 拖动期间忽略，防止与拖动位置冲突
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
          onMouseDown={handleBarMouseDown}
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
