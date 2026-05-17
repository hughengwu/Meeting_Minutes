import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { deleteMeeting, getMeetings, uploadAudio } from '../api'

function formatDate(str) {
  if (!str) return ''
  return new Date(str).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

const STATUS_CONFIG = {
  pending:    { label: '等待中',  dot: 'bg-amber-400',  text: 'text-amber-600',  badge: 'bg-amber-50 text-amber-700 border-amber-200' },
  processing: { label: '处理中',  dot: 'bg-blue-500 animate-pulse', text: 'text-blue-600', badge: 'bg-blue-50 text-blue-700 border-blue-200' },
  done:       { label: '已完成',  dot: 'bg-emerald-500', text: 'text-emerald-600', badge: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  error:      { label: '处理失败', dot: 'bg-red-500',    text: 'text-red-600',    badge: 'bg-red-50 text-red-700 border-red-200' },
}

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${cfg.badge}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

function MeetingCard({ meeting: m, onDelete }) {
  const navigate = useNavigate()
  const isActive = m.status === 'pending' || m.status === 'processing'
  const progress = m.job?.progress || 0
  const stepLabel = m.job?.error_message || ''

  return (
    <div
      className="group bg-white border border-gray-200 rounded-xl p-4 cursor-pointer hover:border-blue-300 hover:shadow-sm transition-all"
      onClick={() => navigate(`/meeting/${m.id}`)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-900 truncate text-sm">{m.title}</span>
          </div>

          {m.status === 'done' && (
            <p className="text-xs text-gray-400">
              {formatDate(m.created_at)}
              {m.speaker_count > 0 && <span> · {m.speaker_count} 位说话人</span>}
              {m.utterance_count > 0 && <span> · {m.utterance_count} 条发言</span>}
            </p>
          )}
          {m.status === 'error' && (
            <p className="text-xs text-red-500 mt-0.5 truncate">{m.job?.error_message}</p>
          )}
          {(m.status === 'pending' || m.status === 'processing') && (
            <p className="text-xs text-gray-400 mt-0.5">{formatDate(m.created_at)}</p>
          )}

          {isActive && (
            <div className="mt-3">
              {stepLabel && (
                <p className="text-xs text-gray-500 mb-1.5 truncate">{stepLabel}</p>
              )}
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                  <div
                    className="bg-blue-500 h-1.5 rounded-full transition-all duration-700"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <span className="text-xs text-gray-400 w-8 text-right">{progress}%</span>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col items-end gap-2 flex-shrink-0">
          <StatusBadge status={m.status} />
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(m.id) }}
            className="text-xs text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  )
}

const FILTERS = [
  { key: 'all',    label: '全部' },
  { key: 'active', label: '处理中' },
  { key: 'done',   label: '已完成' },
  { key: 'error',  label: '失败' },
]

function matchFilter(m, filter) {
  if (filter === 'all') return true
  if (filter === 'active') return m.status === 'pending' || m.status === 'processing'
  return m.status === filter
}

function UploadModal({ file, onConfirm, onCancel }) {
  const [hotwords, setHotwords] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-1">上传音频</h2>
        <p className="text-sm text-gray-400 mb-4 truncate">{file.name}</p>

        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          会议背景 / 热词
          <span className="ml-1.5 text-xs font-normal text-gray-400">（可选，用于提升识别准确率）</span>
        </label>
        <textarea
          value={hotwords}
          onChange={(e) => setHotwords(e.target.value)}
          placeholder={'可填写会议主题、参与者姓名、专业术语等，空格或换行分隔\n例如：张三 李四 Kubernetes 微服务 Q2营收'}
          className="w-full h-28 text-sm border border-gray-200 rounded-xl px-3 py-2.5 text-gray-800 placeholder-gray-300 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          autoFocus
        />
        <p className="text-xs text-gray-400 mt-1.5 mb-5">
          热词会引导模型优先识别这些词汇；背景描述帮助理解语境，两者均可混写。
        </p>

        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            取消
          </button>
          <button
            onClick={() => onConfirm(hotwords)}
            className="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
          >
            开始处理
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Home() {
  const navigate = useNavigate()
  const fileRef = useRef(null)
  const [meetings, setMeetings] = useState([])
  const [filter, setFilter] = useState('all')
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState('')
  const [pendingFile, setPendingFile] = useState(null)

  const load = () => getMeetings().then((r) => setMeetings(r.data)).catch(() => {})

  useEffect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [])

  const pickFile = (file) => {
    if (!file) return
    setPendingFile(file)
  }

  const handleConfirm = async (hotwords) => {
    const file = pendingFile
    setPendingFile(null)
    setUploadError('')
    setUploading(true)
    setUploadProgress(0)
    try {
      const res = await uploadAudio(file, hotwords, setUploadProgress)
      navigate(`/meeting/${res.data.meeting_id}`, { state: { jobId: res.data.job_id } })
    } catch (e) {
      setUploadError(e.response?.data?.detail || '上传失败，请重试')
      setUploading(false)
    }
  }

  const handleCancel = () => {
    setPendingFile(null)
    fileRef.current && (fileRef.current.value = '')
  }

  const handleDelete = async (id) => {
    if (!confirm('确认删除？将同时删除录音文件和日志。')) return
    await deleteMeeting(id)
    setMeetings((prev) => prev.filter((m) => m.id !== id))
  }

  const counts = {
    all:    meetings.length,
    active: meetings.filter((m) => m.status === 'pending' || m.status === 'processing').length,
    done:   meetings.filter((m) => m.status === 'done').length,
    error:  meetings.filter((m) => m.status === 'error').length,
  }

  const filtered = meetings.filter((m) => matchFilter(m, filter))

  return (
    <div className="min-h-screen bg-slate-50">
      {pendingFile && (
        <UploadModal
          file={pendingFile}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      )}
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center text-white text-xs font-bold">
              M
            </div>
            <span className="font-semibold text-gray-900 text-sm">会议记录</span>
          </div>
          <button
            onClick={() => !uploading && fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors font-medium"
          >
            <span className="text-base leading-none">+</span>
            <span>上传音频</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept=".mp3,.wav,.m4a,.flac,.ogg,.mp4,.webm"
            onChange={(e) => pickFile(e.target.files[0])}
          />
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-4 py-6">
        {/* Upload progress */}
        {uploading && (
          <div className="bg-white border border-gray-200 rounded-xl p-4 mb-4 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-gray-700">上传中...</span>
              <span className="text-sm text-gray-500">{uploadProgress}%</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-1.5">
              <div
                className="bg-blue-500 h-1.5 rounded-full transition-all"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}

        {uploadError && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 mb-4 text-red-600 text-sm">
            {uploadError}
          </div>
        )}

        {/* Empty state */}
        {meetings.length === 0 && !uploading && (
          <div
            className={`border-2 border-dashed rounded-2xl py-20 text-center cursor-pointer transition-colors
              ${dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300 bg-white'}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files[0]) }}
            onClick={() => fileRef.current?.click()}
          >
            <div className="text-5xl mb-4">🎙️</div>
            <p className="text-gray-700 font-medium mb-1">拖拽音频文件到此处</p>
            <p className="text-gray-400 text-sm">支持 MP3 · WAV · M4A · FLAC · OGG · MP4</p>
          </div>
        )}

        {/* Drag-over strip when list is visible */}
        {meetings.length > 0 && (
          <div
            className={`border-2 border-dashed rounded-xl p-3 text-center cursor-pointer transition-all mb-4
              ${dragging ? 'border-blue-400 bg-blue-50 text-blue-600' : 'border-transparent hover:border-gray-200 text-gray-400'}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files[0]) }}
          >
            <p className="text-sm">{dragging ? '松开以上传' : '拖拽音频到此处快速上传'}</p>
          </div>
        )}

        {/* Filter tabs */}
        {meetings.length > 0 && (
          <div className="flex items-center gap-0 mb-4 border-b border-gray-200">
            {FILTERS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  filter === tab.key
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.label}
                {counts[tab.key] > 0 && (
                  <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
                    filter === tab.key ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {counts[tab.key]}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        {/* Meeting list */}
        <div className="space-y-2">
          {filtered.map((m) => (
            <MeetingCard key={m.id} meeting={m} onDelete={handleDelete} />
          ))}
          {filtered.length === 0 && meetings.length > 0 && (
            <p className="text-center text-gray-400 text-sm py-10">暂无符合条件的记录</p>
          )}
        </div>
      </div>
    </div>
  )
}
