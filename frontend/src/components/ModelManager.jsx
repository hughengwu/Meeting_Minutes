import { useCallback, useEffect, useState } from 'react'
import { downloadModel, getModels, setActiveModel } from '../api'

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ModelCard({ model, onDownload, onActivate }) {
  const { id, name, tag, description, vram_gb, downloaded, active, download_status: ds } = model
  const isDownloading = ds?.status === 'downloading'
  const hasError = ds?.status === 'error'
  const progress = ds?.progress ?? 0
  const label = ds?.label || ''

  return (
    <div className={`border rounded-xl p-4 transition-colors ${
      active ? 'border-blue-300 bg-blue-50/40' : 'border-gray-200 bg-white'
    }`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-gray-900 text-sm">{name}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            tag === '推荐'
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-gray-100 text-gray-500'
          }`}>
            {tag}
          </span>
          {active && (
            <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 text-blue-700">
              当前使用
            </span>
          )}
        </div>
        <span className="text-xs text-gray-400 flex-shrink-0 mt-0.5">{vram_gb}GB 显存</span>
      </div>

      <p className="text-xs text-gray-500 mb-3">{description}</p>

      {isDownloading && (
        <div className="mb-3">
          {label && <p className="text-xs text-gray-500 mb-1.5">{label}</p>}
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-1.5 bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${Math.max(progress, 4)}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 mt-1 text-right">{progress}%</p>
        </div>
      )}

      {hasError && (
        <p className="text-xs text-red-500 mb-3 break-all">失败: {ds?.error}</p>
      )}

      <div className="flex items-center gap-3">
        {!downloaded && !isDownloading && (
          <button
            onClick={() => onDownload(id)}
            className="px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
          >
            {hasError ? '重新下载' : '下载'}
          </button>
        )}

        {downloaded && !active && (
          <button
            onClick={() => onActivate(id)}
            className="px-3 py-1.5 text-xs font-medium border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
          >
            切换为此模型
          </button>
        )}

        {downloaded && (
          <span className="flex items-center gap-1 text-xs text-emerald-600">
            <CheckIcon />
            已下载
          </span>
        )}

        {isDownloading && (
          <span className="flex items-center gap-1.5 text-xs text-blue-500">
            <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
            下载中...
          </span>
        )}
      </div>
    </div>
  )
}

export default function ModelManager({ onClose }) {
  const [models, setModels] = useState([])

  const load = useCallback(() => {
    getModels().then(r => setModels(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 下载中时每 2 秒轮询，否则每 5 秒
  useEffect(() => {
    const hasDownloading = models.some(m => m.download_status?.status === 'downloading')
    const t = setInterval(load, hasDownloading ? 2000 : 5000)
    return () => clearInterval(t)
  }, [models, load])

  const handleDownload = async (modelId) => {
    await downloadModel(modelId).catch(() => {})
    load()
  }

  const handleActivate = async (modelId) => {
    await setActiveModel(modelId).catch(() => {})
    load()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/30 px-4 pb-4 sm:pb-0"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-6"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-gray-900">ASR 模型设置</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg hover:bg-gray-100 transition-colors"
          >
            ×
          </button>
        </div>

        <div className="space-y-3">
          {models.map(m => (
            <ModelCard
              key={m.id}
              model={m}
              onDownload={handleDownload}
              onActivate={handleActivate}
            />
          ))}
          {models.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-4">加载中...</p>
          )}
        </div>

        <p className="text-xs text-gray-400 mt-4 leading-relaxed">
          切换模型后新任务使用新模型处理，已有转录不受影响。FireRedASR 模式下热词对文本输出暂无效果。
        </p>
      </div>
    </div>
  )
}
