import { useCallback, useEffect, useState } from 'react'
import {
  getLmStudioModels, getTranslationSettings, saveTranslationSettings, testTranslation,
} from '../api'

const LANGS = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'zh-TW', label: '繁体中文' },
  { value: 'en',    label: '英文' },
  { value: 'ja',    label: '日文' },
]

const input =
  'w-full text-sm border border-gray-200 rounded-lg px-3 py-2 text-gray-800 placeholder-gray-300 ' +
  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'

function Field({ label, hint, children }) {
  return (
    <div className="mb-3">
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label}
        {hint && <span className="ml-1.5 font-normal text-gray-400">{hint}</span>}
      </label>
      {children}
    </div>
  )
}

export default function TranslationSettings() {
  const [settings, setSettings] = useState(null)
  const [providers, setProviders] = useState([])
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState(0)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [lmModels, setLmModels] = useState([])
  const [lmError, setLmError] = useState('')

  const load = useCallback(() => {
    getTranslationSettings()
      .then((r) => { setSettings(r.data.settings); setProviders(r.data.providers) })
      .catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  const set = (key, value) => setSettings((s) => ({ ...s, [key]: value }))

  const save = async (patch = null) => {
    setSaving(true)
    try {
      const r = await saveTranslationSettings(patch || settings)
      setSettings(r.data.settings)
      setSavedAt(Date.now())
      setTestResult(null)
    } finally {
      setSaving(false)
    }
  }

  const runTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      await saveTranslationSettings(settings)   // 先落盘再测，保证测的是当前填的配置
      const r = await testTranslation()
      setTestResult(r.data)
    } catch (e) {
      setTestResult({ ok: false, error: e.response?.data?.detail || '请求失败' })
    } finally {
      setTesting(false)
    }
  }

  const loadLmModels = async () => {
    setLmError('')
    await saveTranslationSettings(settings)
    const r = await getLmStudioModels().catch(() => ({ data: { ok: false, error: '请求失败' } }))
    if (r.data.ok) setLmModels(r.data.models)
    else setLmError(r.data.error || '无法连接 LM Studio')
  }

  if (!settings) {
    return <p className="text-sm text-gray-400 text-center py-4">加载中...</p>
  }

  const provider = settings.provider

  return (
    <div>
      <div className="space-y-2 mb-4">
        {providers.map((p) => (
          <button
            key={p.id}
            onClick={() => { set('provider', p.id); save({ ...settings, provider: p.id }) }}
            className={`w-full text-left border rounded-xl p-3 transition-colors ${
              provider === p.id
                ? 'border-blue-300 bg-blue-50/40'
                : 'border-gray-200 bg-white hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-sm font-medium text-gray-900">{p.name}</span>
              {provider === p.id && (
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 text-blue-700">
                  当前使用
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500">{p.description}</p>
          </button>
        ))}
      </div>

      <Field label="目标语言">
        <select
          value={settings.target_lang}
          onChange={(e) => set('target_lang', e.target.value)}
          className={input}
        >
          {LANGS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
        </select>
      </Field>

      {provider === 'google_v2' && (
        <Field label="Google API Key" hint="Google Cloud Translation v2">
          <input
            type="password"
            value={settings.google_api_key}
            onChange={(e) => set('google_api_key', e.target.value)}
            placeholder="AIza..."
            className={input}
          />
        </Field>
      )}

      {provider.startsWith('google') && (
        <Field label="HTTP 代理" hint="（可选）国内访问 Google 通常需要，例如 http://127.0.0.1:7890">
          <input
            value={settings.proxy}
            onChange={(e) => set('proxy', e.target.value)}
            placeholder="留空则使用系统 / 环境变量代理"
            className={input}
          />
        </Field>
      )}

      {provider === 'lmstudio' && (
        <>
          <Field label="接口地址" hint="LM Studio → Developer → Server 里的地址">
            <input
              value={settings.lmstudio_base_url}
              onChange={(e) => set('lmstudio_base_url', e.target.value)}
              placeholder="http://localhost:1234/v1"
              className={input}
            />
          </Field>
          <Field label="模型" hint="留空则用服务端已加载的第一个模型">
            <div className="flex gap-2">
              {lmModels.length > 0 ? (
                <select
                  value={settings.lmstudio_model}
                  onChange={(e) => set('lmstudio_model', e.target.value)}
                  className={input}
                >
                  <option value="">（自动选择）</option>
                  {lmModels.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : (
                <input
                  value={settings.lmstudio_model}
                  onChange={(e) => set('lmstudio_model', e.target.value)}
                  placeholder="qwen2.5-7b-instruct"
                  className={input}
                />
              )}
              <button
                onClick={loadLmModels}
                className="px-3 py-2 text-xs font-medium border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors whitespace-nowrap"
              >
                获取列表
              </button>
            </div>
            {lmError && <p className="text-xs text-red-500 mt-1 break-all">{lmError}</p>}
          </Field>
        </>
      )}

      <div className="flex items-center gap-2 mt-4">
        <button
          onClick={() => save()}
          disabled={saving}
          className="px-4 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition-colors"
        >
          {saving ? '保存中...' : '保存'}
        </button>
        <button
          onClick={runTest}
          disabled={testing}
          className="px-4 py-1.5 text-xs font-medium border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          {testing ? '测试中...' : '测试连接'}
        </button>
        {savedAt > 0 && !saving && (
          <span className="text-xs text-emerald-600">已保存</span>
        )}
      </div>

      {testResult && (
        <div className={`mt-3 rounded-xl border p-3 text-xs ${
          testResult.ok
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-red-50 border-red-200 text-red-600'
        }`}>
          {testResult.ok ? (
            <>
              <p className="mb-1 opacity-70">测试成功，译文：</p>
              <p className="font-medium break-all">{testResult.translated}</p>
            </>
          ) : (
            <p className="break-all">失败：{testResult.error}</p>
          )}
        </div>
      )}

      <p className="text-xs text-gray-400 mt-4 leading-relaxed">
        翻译只影响字幕的译文列，不会改动识别原文。已是目标语言的片段会自动跳过，不消耗额度。
      </p>
    </div>
  )
}
