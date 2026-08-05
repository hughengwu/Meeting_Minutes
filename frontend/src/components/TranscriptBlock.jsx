import { forwardRef, useState } from 'react'

function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const TranscriptBlock = forwardRef(function TranscriptBlock(
  { utterance, speakerName, color, onSpeakerClick, onTextSave, isActive, onSeek, showTranslation },
  ref
) {
  const [editing, setEditing] = useState('')   // '' | 'text' | 'text_zh'
  const [draft, setDraft] = useState('')

  const startEdit = (field) => {
    setDraft(utterance[field] || '')
    setEditing(field)
  }

  const save = () => {
    const field = editing
    setEditing('')
    if (draft.trim() !== (utterance[field] || '')) {
      onTextSave(utterance.id, { [field]: draft.trim() })
    }
  }

  const editor = (
    <textarea
      className="w-full bg-white text-gray-900 rounded-lg px-3 py-2 text-sm resize-none border border-gray-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => { if (e.key === 'Escape') setEditing('') }}
      autoFocus
      rows={Math.max(2, Math.ceil(draft.length / 40))}
    />
  )

  const hasZh = !!(utterance.text_zh || '').trim()

  return (
    <div
      ref={ref}
      className={`flex gap-4 px-4 py-3 group transition-all duration-300 border-l-2 ${
        isActive
          ? 'bg-blue-50 border-blue-400'
          : 'border-transparent hover:bg-slate-50'
      }`}
    >
      {/* Speaker + time（字幕模式没有说话人，只显示时间） */}
      <div className={`flex-shrink-0 pt-0.5 text-right ${color ? 'w-20' : 'w-12'}`}>
        {color && (
          <button
            onClick={onSpeakerClick}
            className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium border
              ${color.bg} ${color.text} ${color.border}
              hover:shadow-sm transition-all`}
          >
            {speakerName}
          </button>
        )}
        <div
          className={`text-xs transition-colors ${color ? 'mt-1' : ''} ${
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
        {editing === 'text' ? editor : (
          <p
            className={`text-sm leading-relaxed cursor-pointer rounded px-1 py-0.5 -ml-1 transition-colors ${
              isActive ? 'text-gray-900' : 'text-gray-800 hover:bg-gray-100'
            }`}
            onClick={() => onSeek?.(utterance.start)}
            onDoubleClick={() => startEdit('text')}
            title="单击跳转 · 双击编辑"
          >
            {utterance.text}
          </p>
        )}

        {showTranslation && (editing === 'text_zh' ? (
          <div className="mt-1.5">{editor}</div>
        ) : hasZh ? (
          <p
            className="mt-1 text-sm leading-relaxed text-blue-700/80 cursor-pointer rounded px-1 py-0.5 -ml-1 border-l-2 border-blue-200 pl-2 hover:bg-blue-50/60 transition-colors"
            onClick={() => onSeek?.(utterance.start)}
            onDoubleClick={() => startEdit('text_zh')}
            title="译文 · 单击跳转 · 双击编辑"
          >
            {utterance.text_zh}
          </p>
        ) : (
          <p
            className="mt-1 text-xs text-gray-300 cursor-pointer hover:text-blue-500 transition-colors"
            onClick={() => startEdit('text_zh')}
            title="点击手动补充译文"
          >
            + 添加译文
          </p>
        ))}
      </div>
    </div>
  )
})

export default TranscriptBlock
