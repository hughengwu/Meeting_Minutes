import { useState } from 'react'

function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function TranscriptBlock({ utterance, speakerName, color, onSpeakerClick, onTextSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(utterance.text)

  const save = () => {
    setEditing(false)
    if (draft.trim() !== utterance.text) {
      onTextSave(utterance.id, draft.trim())
    }
  }

  return (
    <div className="flex gap-4 px-4 py-3 group hover:bg-slate-50 transition-colors">
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
        <div className="text-xs text-gray-400 mt-1">
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
            className="text-gray-800 text-sm leading-relaxed cursor-text rounded px-1 py-0.5 -ml-1 hover:bg-gray-100 transition-colors"
            onClick={() => { setDraft(utterance.text); setEditing(true) }}
            title="点击编辑"
          >
            {utterance.text}
          </p>
        )}
      </div>
    </div>
  )
}
