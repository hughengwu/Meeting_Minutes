import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const uploadAudio = (file, hotwords, onProgress, autoTranslate = false, mode = 'meeting') => {
  const form = new FormData()
  form.append('file', file)
  if (hotwords) form.append('hotwords', hotwords)
  if (autoTranslate) form.append('translate', '1')
  form.append('mode', mode)
  return api.post('/upload', form, {
    onUploadProgress: (e) => onProgress(Math.round((e.loaded * 100) / e.total)),
  })
}

export const getMeetings = () => api.get('/meetings/')
export const getMeeting = (id) => api.get(`/meetings/${id}`)
export const updateTitle = (id, title) => api.patch(`/meetings/${id}/title`, { title })
export const updateSpeakerNames = (id, speaker_names) =>
  api.patch(`/meetings/${id}/speakers`, { speaker_names })
export const updateUtterance = (meetingId, utteranceId, payload) =>
  api.patch(
    `/meetings/${meetingId}/utterances/${utteranceId}`,
    typeof payload === 'string' ? { text: payload } : payload,
  )
export const deleteMeeting = (id) => api.delete(`/meetings/${id}`)
export const exportMeeting = (id, format, lang = 'original', speaker = false) =>
  api.get(`/meetings/${id}/export`, { params: { format, lang, speaker } })
export const translateMeeting = (id, force = false) =>
  api.post(`/meetings/${id}/translate`, { force })
export const getMeetingLogs = (id) => api.get(`/meetings/${id}/logs`)
export const getJob = (id) => api.get(`/jobs/${id}`)

export const audioUrl = (meetingId) => `/api/meetings/${meetingId}/audio`

export const getModels = () => api.get('/models/')
export const downloadModel = (modelId) => api.post(`/models/${modelId}/download`)
export const getModelStatus = (modelId) => api.get(`/models/${modelId}/status`)
export const setActiveModel = (modelId) => api.post('/models/active', { model_id: modelId })

export const getTranslationSettings = () => api.get('/translation/settings')
export const saveTranslationSettings = (patch) => api.post('/translation/settings', patch)
export const testTranslation = (text) => api.post('/translation/test', text ? { text } : {})
export const getLmStudioModels = () => api.get('/translation/lmstudio/models')
