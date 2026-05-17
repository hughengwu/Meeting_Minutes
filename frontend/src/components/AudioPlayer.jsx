import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { audioUrl } from '../api'

function fmtTime(s) {
  if (!isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

const AudioPlayer = forwardRef(function AudioPlayer({ meetingId, onTimeUpdate }, ref) {
  const audioRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [dragging, setDragging] = useState(false)

  useImperativeHandle(ref, () => ({
    seek(time) {
      if (!audioRef.current) return
      audioRef.current.currentTime = time
      setCurrent(time)
    },
  }))

  const toggle = () => {
    const el = audioRef.current
    if (!el) return
    playing ? el.pause() : el.play()
  }

  const seek = (e) => {
    const el = audioRef.current
    if (!el || !duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    el.currentTime = ratio * duration
    setCurrent(ratio * duration)
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
          const t = e.target.currentTime
          if (!dragging) setCurrent(t)
          onTimeUpdate?.(t)
        }}
        onLoadedMetadata={(e) => setDuration(e.target.duration)}
      />

      <div className="flex items-center gap-3">
        {/* Play/Pause */}
        <button
          onClick={toggle}
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
          className="flex-1 h-1.5 bg-gray-200 rounded-full cursor-pointer relative group"
          onClick={seek}
          onMouseDown={() => setDragging(true)}
          onMouseUp={() => setDragging(false)}
          onMouseMove={(e) => {
            if (!dragging) return
            const rect = e.currentTarget.getBoundingClientRect()
            const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
            setCurrent(ratio * duration)
            if (audioRef.current) audioRef.current.currentTime = ratio * duration
          }}
        >
          <div
            className="h-1.5 bg-blue-500 rounded-full relative"
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
