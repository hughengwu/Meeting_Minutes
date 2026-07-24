import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const uploadAudio = (file, hotwords, onProgress) => {
  const form = new FormData()
  form.append('file', file)
  if (hotwords) form.append('hotwords', hotwords)
  return api.post('/upload', form, {
    onUploadProgress: (e) => onProgress(Math.round((e.loaded * 100) / e.total)),
  })
}

export const getMeetings = () => api.get('/meetings/')
export const getMeeting = (id) => api.get(`/meetings/${id}`)
export const updateTitle = (id, title) => api.patch(`/meetings/${id}/title`, { title })
export const updateSpeakerNames = (id, speaker_names) =>
  api.patch(`/meetings/${id}/speakers`, { speaker_names })
export const updateUtterance = (meetingId, utteranceId, text) =>
  api.patch(`/meetings/${meetingId}/utterances/${utteranceId}`, { text })
export const deleteMeeting = (id) => api.delete(`/meetings/${id}`)
export const exportMeeting = (id, format) =>
  api.get(`/meetings/${id}/export`, { params: { format } })
export const getMeetingLogs = (id) => api.get(`/meetings/${id}/logs`)
export const getJob = (id) => api.get(`/jobs/${id}`)

export const audioUrl = (meetingId) => `/api/meetings/${meetingId}/audio`

export const getModels = () => api.get('/models/')
export const downloadModel = (modelId) => api.post(`/models/${modelId}/download`)
export const getModelStatus = (modelId) => api.get(`/models/${modelId}/status`)
export const setActiveModel = (modelId) => api.post('/models/active', { model_id: modelId })
