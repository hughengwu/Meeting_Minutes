import { useEffect, useState } from 'react'

function useElapsed() {
  const [sec, setSec] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSec((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  return sec
}

function fmtElapsed(sec) {
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m ${sec % 60}s`
}

export default function ProcessingStatus({ status, job }) {
  const progress = job?.progress || 0
  const label = (status === 'processing' && job?.error_message) || '等待处理...'
  const elapsed = useElapsed()

  if (status === 'error') {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-5">
        <p className="text-red-700 font-medium mb-1">处理失败</p>
        {job?.error_message && (
          <p className="text-red-600 text-sm font-mono break-all">{job.error_message}</p>
        )}
      </div>
    )
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 mb-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-gray-800">{label}</span>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>{fmtElapsed(elapsed)}</span>
          <span className="font-medium text-gray-600">{progress}%</span>
        </div>
      </div>

      <div className="w-full bg-gray-100 rounded-full h-2">
        <div
          className="bg-blue-500 h-2 rounded-full transition-all duration-700"
          style={{ width: `${Math.max(progress, 3)}%` }}
        />
      </div>

      <p className="text-xs text-gray-400 mt-2.5">
        {status === 'pending'
          ? '任务已排队，等待 GPU 处理...'
          : '模型首次加载需 30–60 秒，转录速度约为音频时长的 1/5'}
      </p>
    </div>
  )
}
