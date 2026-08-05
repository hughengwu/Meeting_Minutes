import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  deleteMeeting, getMeeting, getJob, translateMeeting,
  updateSpeakerNames, updateTitle, updateUtterance,
} from '../api'
import AudioPlayer from '../components/AudioPlayer'
import ExportPanel from '../components/ExportPanel'
import LogViewer from '../components/LogViewer'
import ProcessingStatus from '../components/ProcessingStatus'
import TranscriptBlock from '../components/TranscriptBlock'

const SPEAKER_COLORS = [
  { bg: 'bg-blue-50',    text: 'text-blue-700',    border: 'border-blue-200' },
  { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
  { bg: 'bg-purple-50',  text: 'text-purple-700',  border: 'border-purple-200' },
  { bg: 'bg-orange-50',  text: 'text-orange-700',  border: 'border-orange-200' },
  { bg: 'bg-pink-50',    text: 'text-pink-700',    border: 'border-pink-200' },
  { bg: 'bg-teal-50',    text: 'text-teal-700',    border: 'border-teal-200' },
]

export default function Meeting() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const jobId = location.state?.jobId

  const [meeting, setMeeting] = useState(null)
  const [job, setJob] = useState(null)
  const [translateJob, setTranslateJob] = useState(null)
  const [translateError, setTranslateError] = useState('')
  const [showTranslation, setShowTranslation] = useState(true)
  const [activeTab, setActiveTab] = useState('transcript')
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [renameModal, setRenameModal] = useState(null)
  const [renameDraft, setRenameDraft] = useState('')
  const renameInputRef = useRef(null)

  // 音频同步
  const [currentTime, setCurrentTime] = useState(0)
  const [autoScroll, setAutoScroll] = useState(true)
  const audioPlayerRef = useRef(null)
  const blockRefs = useRef({})
  const scrollTimerRef = useRef(null)

  const activeId = useMemo(() => {
    if (!meeting?.utterances) return null
    const u = meeting.utterances.find(u => currentTime >= u.start && currentTime < u.end)
    return u?.id ?? null
  }, [currentTime, meeting?.utterances])

  // 自动滚动到当前激活段
  useEffect(() => {
    if (!autoScroll || activeId === null) return
    blockRefs.current[activeId]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeId, autoScroll])

  // 用户手动滚动时暂停自动滚动 3 秒
  useEffect(() => {
    const onScroll = () => {
      setAutoScroll(false)
      clearTimeout(scrollTimerRef.current)
      scrollTimerRef.current = setTimeout(() => setAutoScroll(true), 3000)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      clearTimeout(scrollTimerRef.current)
    }
  }, [])

  const seekTo = useCallback((time) => {
    audioPlayerRef.current?.seek(time)
  }, [])

  const loadMeeting = useCallback(() =>
    getMeeting(id).then((r) => {
      setMeeting(r.data)
      if (r.data.job) setJob(r.data.job)
      setTranslateJob(r.data.translate_job || null)
    }).catch(() => {}), [id])

  useEffect(() => { loadMeeting() }, [loadMeeting])

  // 翻译任务在后台队列里跑，进行中时持续轮询会议详情拿进度和译文
  const translating =
    translateJob?.status === 'pending' || translateJob?.status === 'processing'

  useEffect(() => {
    if (!translating) return
    const t = setInterval(loadMeeting, 2000)
    return () => clearInterval(t)
  }, [translating, loadMeeting])

  useEffect(() => {
    if (!meeting) return
    if (meeting.status === 'done' || meeting.status === 'error') return

    const poll = async () => {
      if (jobId) {
        try {
          const r = await getJob(jobId)
          setJob(r.data)
          if (r.data.status === 'done' || r.data.status === 'error') loadMeeting()
        } catch {}
      } else {
        loadMeeting()
      }
    }

    const t = setInterval(poll, 2000)
    return () => clearInterval(t)
  }, [meeting?.status, jobId, loadMeeting])

  const speakerIndex = {}
  let colorIdx = 0
  for (const u of meeting?.utterances || []) {
    if (u.speaker && !(u.speaker in speakerIndex)) speakerIndex[u.speaker] = colorIdx++
  }
  const getSpeakerName = (sid) => meeting?.speaker_names?.[sid] || sid
  const getColor = (sid) => SPEAKER_COLORS[speakerIndex[sid] % SPEAKER_COLORS.length]

  const saveTitle = async () => {
    setEditingTitle(false)
    if (titleDraft !== meeting.title) {
      await updateTitle(id, titleDraft)
      setMeeting((m) => ({ ...m, title: titleDraft }))
    }
  }

  const openRename = (speakerId) => {
    setRenameModal({ speakerId })
    setRenameDraft(getSpeakerName(speakerId))
    setTimeout(() => renameInputRef.current?.focus(), 50)
  }

  const saveRename = async () => {
    const { speakerId } = renameModal
    const next = { ...(meeting.speaker_names || {}), [speakerId]: renameDraft }
    setMeeting((m) => ({ ...m, speaker_names: next }))
    setRenameModal(null)
    await updateSpeakerNames(id, next)
  }

  const saveUtterance = async (utteranceId, patch) => {
    setMeeting((m) => ({
      ...m,
      utterances: m.utterances.map((u) => u.id === utteranceId ? { ...u, ...patch } : u),
    }))
    await updateUtterance(id, utteranceId, patch)
  }

  const startTranslate = async (force = false) => {
    setTranslateError('')
    try {
      await translateMeeting(id, force)
      setTranslateJob({ status: 'pending', progress: 0, error_message: null })
      loadMeeting()
    } catch (e) {
      setTranslateError(e.response?.data?.detail || '发起翻译失败')
    }
  }

  const handleDelete = async () => {
    if (!confirm('确认删除？将同时删除录音文件和日志。')) return
    await deleteMeeting(id)
    navigate('/')
  }

  if (!meeting) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <p className="text-gray-400 text-sm">加载中...</p>
      </div>
    )
  }

  const isProcessing = meeting.status === 'pending' || meeting.status === 'processing'
  const isDone = meeting.status === 'done'
  // 字幕模式没有说话人信息（speaker 为 null），相关 UI 整体隐藏
  const isSubtitleMode = meeting.mode === 'subtitle'
  const uniqueSpeakers = [
    ...new Set((meeting.utterances || []).map((u) => u.speaker).filter(Boolean)),
  ]
  const total = (meeting.utterances || []).length
  const translatedCount = meeting.translated_count || 0
  const hasTranslation = translatedCount > 0

  const tabs = [
    { key: 'transcript', label: isSubtitleMode ? '字幕内容' : '转录内容', disabled: !isDone },
    { key: 'logs',       label: '处理日志' },
  ]

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-white border-b border-gray-200">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center gap-3">
          <button
            onClick={() => navigate('/')}
            className="text-gray-400 hover:text-gray-700 text-sm transition-colors flex-shrink-0 flex items-center gap-1"
          >
            ← 返回
          </button>

          <div className="flex-1 min-w-0">
            {editingTitle ? (
              <input
                className="w-full bg-gray-50 text-gray-900 px-2 py-1 rounded-lg text-sm font-medium border border-gray-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={saveTitle}
                onKeyDown={(e) => e.key === 'Enter' && saveTitle()}
                autoFocus
              />
            ) : (
              <p
                className="text-sm font-semibold text-gray-900 truncate cursor-pointer hover:text-blue-600 transition-colors"
                onClick={() => { setTitleDraft(meeting.title); setEditingTitle(true) }}
                title="点击编辑标题"
              >
                {meeting.title}
              </p>
            )}
          </div>

          {isDone && (
            <ExportPanel
              meetingId={id}
              hasTranslation={hasTranslation}
              hasSpeakers={uniqueSpeakers.length > 0}
            />
          )}
          <button
            onClick={handleDelete}
            className="text-xs text-gray-300 hover:text-red-500 transition-colors flex-shrink-0 ml-1"
          >
            删除
          </button>
        </div>
      </div>

      {/* Sticky audio player — sticks just below the header (top-14 = 3.5rem = header height) */}
      {isDone && (
        <div className="sticky top-14 z-10 bg-slate-50 border-b border-gray-100">
          <div className="max-w-3xl mx-auto px-4 pt-4 pb-1">
            <AudioPlayer
              ref={audioPlayerRef}
              meetingId={id}
              onTimeUpdate={setCurrentTime}
            />
          </div>
        </div>
      )}

      <div className="max-w-3xl mx-auto px-4 py-6">
        {isProcessing && <ProcessingStatus status={meeting.status} job={job} />}

        {/* Tab nav */}
        <div className="flex gap-0 mb-5 border-b border-gray-200">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => !tab.disabled && setActiveTab(tab.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              } ${tab.disabled ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Transcript tab */}
        {activeTab === 'transcript' && isDone && (
          <>
            {/* 字幕翻译 */}
            <div className="mb-3 px-3 py-2.5 bg-white rounded-xl border border-gray-200">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-gray-400">字幕翻译：</span>

                {translating ? (
                  <>
                    <span className="flex items-center gap-1.5 text-xs text-blue-600">
                      <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
                      {translateJob?.error_message || '翻译中...'}
                    </span>
                    <div className="flex-1 min-w-[120px] bg-gray-100 rounded-full h-1.5">
                      <div
                        className="bg-blue-500 h-1.5 rounded-full transition-all duration-700"
                        style={{ width: `${translateJob?.progress || 0}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400">{translateJob?.progress || 0}%</span>
                  </>
                ) : (
                  <>
                    <span className="text-xs text-gray-600">
                      {hasTranslation ? `已翻译 ${translatedCount}/${total} 条` : '尚未翻译'}
                    </span>
                    <button
                      onClick={() => startTranslate(false)}
                      className="px-3 py-1 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                    >
                      {hasTranslation
                        ? (translatedCount < total ? '继续翻译剩余部分' : '补翻新增片段')
                        : '翻译成中文'}
                    </button>
                    {hasTranslation && (
                      <button
                        onClick={() => startTranslate(true)}
                        className="px-3 py-1 text-xs font-medium border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                      >
                        全部重译
                      </button>
                    )}
                    {hasTranslation && (
                      <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer ml-auto">
                        <input
                          type="checkbox"
                          checked={showTranslation}
                          onChange={(e) => setShowTranslation(e.target.checked)}
                          className="w-3.5 h-3.5 accent-blue-600"
                        />
                        显示译文
                      </label>
                    )}
                  </>
                )}
              </div>

              {(translateError || translateJob?.status === 'error') && (
                <p className="text-xs text-red-500 mt-2 break-all">
                  {translateError || `翻译失败：${translateJob?.error_message || '未知错误'}`}
                  <span className="text-gray-400 ml-1">（可在首页右上角设置里检查翻译服务配置）</span>
                </p>
              )}
            </div>

            {uniqueSpeakers.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 mb-5 px-3 py-2.5 bg-white rounded-xl border border-gray-200">
                <span className="text-xs text-gray-400">说话人：</span>
                {uniqueSpeakers.map((sid) => {
                  const c = getColor(sid)
                  return (
                    <button
                      key={sid}
                      onClick={() => openRename(sid)}
                      className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border
                        ${c.bg} ${c.text} ${c.border} hover:shadow-sm transition-all`}
                      title="点击重命名"
                    >
                      {getSpeakerName(sid)}
                      <span className="opacity-40 text-xs">✎</span>
                    </button>
                  )
                })}
              </div>
            )}

            <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
              {(meeting.utterances || []).map((u) => (
                <TranscriptBlock
                  key={u.id}
                  ref={(el) => {
                    if (el) blockRefs.current[u.id] = el
                    else delete blockRefs.current[u.id]
                  }}
                  utterance={u}
                  speakerName={u.speaker ? getSpeakerName(u.speaker) : ''}
                  color={u.speaker ? getColor(u.speaker) : null}
                  onSpeakerClick={() => u.speaker && openRename(u.speaker)}
                  onTextSave={saveUtterance}
                  isActive={u.id === activeId}
                  onSeek={seekTo}
                  showTranslation={showTranslation}
                />
              ))}
            </div>
          </>
        )}

        {activeTab === 'logs' && (
          <LogViewer meetingId={id} isProcessing={isProcessing} />
        )}
      </div>

      {/* Rename modal */}
      {renameModal && (
        <div
          className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
          onClick={() => setRenameModal(null)}
        >
          <div
            className="bg-white rounded-2xl p-6 w-80 shadow-xl border border-gray-200"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-gray-900 font-semibold mb-1">重命名说话人</h3>
            <p className="text-gray-400 text-xs mb-4 font-mono">{renameModal.speakerId}</p>
            <input
              ref={renameInputRef}
              className="w-full bg-gray-50 text-gray-900 rounded-lg px-3 py-2 text-sm border border-gray-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 mb-4"
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && saveRename()}
              placeholder="输入名字..."
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setRenameModal(null)}
                className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
              >
                取消
              </button>
              <button
                onClick={saveRename}
                className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors font-medium"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
