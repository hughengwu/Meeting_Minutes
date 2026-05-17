import { forwardRef, useState } from 'react'

function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const TranscriptBlock = forwardRef(function TranscriptBlock(
  { utterance, speakerName, color, onSpeakerClick, onTextSave, isActive, onSeek },
  ref
) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(utterance.text)

  const save = () => {
    setEditing(false)
    if (draft.trim() !== utterance.text) {
      onTextSave(utterance.id, draft.trim())
    }
  }

  return (
    <div
      ref={ref}
      className={`flex gap-4 px-4 py-3 group transition-all duration-300 border-l-2 ${
        isActive
          ? 'bg-blue-50 border-blue-400'
          : 'border-transparent hover:bg-slate-50'
      }`}
    >
      {/* Speaker + time */}
      <div className="flex-shrink-0 w-20 pt-0.5 text-right">
        <button
          onClick={onSpeakerClick}
          className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium border
            ${color.bg} ${color.text} ${color.border}
            hover:shadow-sm transition-all`}
        >
          {speakerName}
        </button>
        <div
          className={`text-xs mt-1 transition-colors ${
            isActive
              ? 'text-blue-500 font-medium cursor-pointer'
              : 'text-gray-400 cursor-pointer hover:text-blue-500'
          }`}
          onClick={() => onSeek?.(utterance.start)}
          title="点击跳转到此处"
        >
          {formatTime(utterance.start)}
        </div>
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        {editing ? (
          <textarea
            className="w-full bg-white text-gray-900 rounded-lg px-3 py-2 text-sm resize-none border border-gray-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === 'Escape') { setEditing(false); setDraft(utterance.text) }
            }}
            autoFocus
            rows={Math.max(2, Math.ceil(draft.length / 40))}
          />
        ) : (
          <p
            className={`text-sm leading-relaxed cursor-pointer rounded px-1 py-0.5 -ml-1 transition-colors ${
              isActive ? 'text-gray-900' : 'text-gray-800 hover:bg-gray-100'
            }`}
            onClick={() => onSeek?.(utterance.start)}
            onDoubleClick={() => { setDraft(utterance.text); setEditing(true) }}
            title="单击跳转 · 双击编辑"
          >
            {utterance.text}
          </p>
        )}
      </div>
    </div>
  )
})

export default TranscriptBlock
