/**
 * Typed API calls, grouped by backend router. Mirrors
 * `backend/app/api/routers/*.py` one module section at a time so a new
 * backend endpoint has an obvious home here.
 */

import { api } from "./client";
import type {
  AITaskType,
  AudioPresetInfo,
  BrowseResult,
  ImportedAssetResponse,
  Job,
  JobAcceptedResponse,
  JobLogLine,
  Language,
  ListResponse,
  MediaAsset,
  MediaCapabilities,
  ModelRecommendation,
  ModelSpec,
  OperationResponse,
  Project,
  ProjectStatus,
  PromptInfo,
  ProviderInfo,
  SettingsPayload,
  SpeakingStyle,
  SubtitleCue,
  SubtitleFormat,
  SubtitleStyle,
  SubtitleTrack,
  SystemStatus,
  TaskInfo,
  TextDocument,
  TranscriptionProviderInfo,
  TTSProviderInfo,
  VoiceSpec,
} from "./types";

// -- projects --------------------------------------------------------------

export const projectsApi = {
  list: (params?: { status?: ProjectStatus; search?: string }) =>
    api.get<ListResponse<Project>>("/projects", params),
  get: (id: string) => api.get<Project>(`/projects/${id}`),
  create: (data: { name: string; description?: string }) =>
    api.post<Project>("/projects", data),
  update: (id: string, data: Partial<{ name: string; description: string; status: ProjectStatus }>) =>
    api.patch<Project>(`/projects/${id}`, data),
  delete: (id: string, deleteFiles = false) =>
    api.delete<OperationResponse>(`/projects/${id}`, { delete_files: deleteFiles }),
};

// -- assets ------------------------------------------------------------

export const assetsApi = {
  list: (projectId: string, type?: string) =>
    api.get<ListResponse<MediaAsset>>(`/projects/${projectId}/assets`, { type }),
  import: (projectId: string, path: string, type: string, copyIntoProject = false) =>
    api.post<ImportedAssetResponse>(`/projects/${projectId}/assets/import`, {
      path,
      type,
      copy_into_project: copyIntoProject,
    }),
  upload: (projectId: string, file: File, type: string) =>
    api.upload<ImportedAssetResponse>(`/projects/${projectId}/assets/upload`, file, { type }),
  delete: (projectId: string, assetId: string, deleteFile = false) =>
    api.delete<OperationResponse>(`/projects/${projectId}/assets/${assetId}`, {
      delete_file: deleteFile,
    }),
};

// -- documents ---------------------------------------------------------

export const documentsApi = {
  list: (projectId: string, type?: string) =>
    api.get<ListResponse<TextDocument>>(`/projects/${projectId}/documents`, { type }),
  get: (projectId: string, documentId: string) =>
    api.get<TextDocument>(`/projects/${projectId}/documents/${documentId}`),
  create: (
    projectId: string,
    data: { type: string; title?: string; content: string; language?: Language; source_document_id?: string },
  ) => api.post<TextDocument>(`/projects/${projectId}/documents`, data),
  update: (projectId: string, documentId: string, data: Partial<{ title: string; content: string; language: Language }>) =>
    api.patch<TextDocument>(`/projects/${projectId}/documents/${documentId}`, data),
  delete: (projectId: string, documentId: string) =>
    api.delete<OperationResponse>(`/projects/${projectId}/documents/${documentId}`),
};

// -- jobs (feature actions) --------------------------------------------

export const jobsApi = {
  extractAudio: (projectId: string, assetId: string, preset?: string) =>
    api.post<JobAcceptedResponse>(`/projects/${projectId}/audio/extract`, {
      asset_id: assetId,
      preset,
    }),

  transcribe: (
    projectId: string,
    data: {
      asset_id: string;
      language?: Language;
      model_size?: string;
      auto_detect_language?: boolean;
      refine?: boolean;
      ai_model?: string;
    },
  ) => api.post<JobAcceptedResponse>(`/projects/${projectId}/transcribe`, data),

  processText: (
    projectId: string,
    data: {
      task: AITaskType;
      document_id?: string;
      content?: string;
      prompt?: string;
      source_language?: Language;
      target_language?: Language;
      provider?: string;
      model?: string;
      save?: boolean;
    },
  ) => api.post<JobAcceptedResponse>(`/projects/${projectId}/text/process`, data),

  generateSubtitles: (
    projectId: string,
    data: {
      document_id?: string;
      text?: string;
      segments?: Array<{ index: number; start: number; end: number; text: string }>;
      job_id?: string;
      track_id?: string;
      language?: Language;
      name?: string;
      duration_seconds?: number;
    },
  ) => api.post<JobAcceptedResponse>(`/projects/${projectId}/subtitles/generate`, data),

  renderSubtitles: (
    projectId: string,
    data: { track_id: string; asset_id: string; quality?: string; export_subtitle?: boolean },
  ) => api.post<JobAcceptedResponse>(`/projects/${projectId}/subtitles/render`, data),

  synthesizeSpeech: (
    projectId: string,
    data: {
      segments?: Array<{ kind: string; id?: string; text?: string; seconds?: number }>;
      document_id?: string;
      text?: string;
      voice_id?: string;
      language?: Language;
      style?: SpeakingStyle;
      rate?: number;
      pitch?: number;
      output_format?: string;
      name?: string;
    },
  ) => api.post<JobAcceptedResponse>(`/projects/${projectId}/speech/synthesize`, data),

  list: (params?: { project_id?: string; status?: string; type?: string }) =>
    api.get<ListResponse<Job>>("/jobs", params),
  listActive: () => api.get<ListResponse<Job>>("/jobs/active"),
  get: (jobId: string) => api.get<Job>(`/jobs/${jobId}`),
  logs: (jobId: string, limit = 5000) =>
    api.get<ListResponse<JobLogLine>>(`/jobs/${jobId}/logs`, { limit }),
  cancel: (jobId: string) => api.delete<OperationResponse>(`/jobs/${jobId}`),
};

// -- subtitles -----------------------------------------------------------

export const subtitlesApi = {
  listTracks: (projectId: string) =>
    api.get<ListResponse<SubtitleTrack>>(`/projects/${projectId}/subtitles`),
  createTrack: (projectId: string, data: { name?: string; language?: Language; style?: Partial<SubtitleStyle> }) =>
    api.post<SubtitleTrack>(`/projects/${projectId}/subtitles`, data),
  getTrack: (projectId: string, trackId: string) =>
    api.get<SubtitleTrack>(`/projects/${projectId}/subtitles/${trackId}`),
  updateTrack: (
    projectId: string,
    trackId: string,
    data: Partial<{ name: string; language: Language; style: SubtitleStyle }>,
  ) => api.patch<SubtitleTrack>(`/projects/${projectId}/subtitles/${trackId}`, data),
  deleteTrack: (projectId: string, trackId: string) =>
    api.delete<OperationResponse>(`/projects/${projectId}/subtitles/${trackId}`),

  listCues: (projectId: string, trackId: string) =>
    api.get<ListResponse<SubtitleCue>>(`/projects/${projectId}/subtitles/${trackId}/cues`),
  addCue: (projectId: string, trackId: string, data: { start: number; end: number; text: string; index?: number }) =>
    api.post<SubtitleCue>(`/projects/${projectId}/subtitles/${trackId}/cues`, data),
  updateCue: (
    projectId: string,
    trackId: string,
    cueId: string,
    data: Partial<{ start: number; end: number; text: string }>,
  ) => api.patch<SubtitleCue>(`/projects/${projectId}/subtitles/${trackId}/cues/${cueId}`, data),
  deleteCue: (projectId: string, trackId: string, cueId: string) =>
    api.delete<OperationResponse>(`/projects/${projectId}/subtitles/${trackId}/cues/${cueId}`),
  splitCue: (projectId: string, trackId: string, cueId: string, atSeconds: number) =>
    api.post<ListResponse<SubtitleCue>>(`/projects/${projectId}/subtitles/${trackId}/cues/${cueId}/split`, {
      at_seconds: atSeconds,
    }),
  mergeCue: (projectId: string, trackId: string, cueId: string) =>
    api.post<ListResponse<SubtitleCue>>(`/projects/${projectId}/subtitles/${trackId}/cues/${cueId}/merge`, {}),

  previewUrl: (projectId: string, trackId: string, format: SubtitleFormat) =>
    `/api/projects/${projectId}/subtitles/${trackId}/preview?format=${format}`,
  export: (projectId: string, trackId: string, format: SubtitleFormat) =>
    api.post<OperationResponse>(`/projects/${projectId}/subtitles/${trackId}/export`, { format }),
};

// -- AI discovery --------------------------------------------------------

export const aiApi = {
  providers: (refresh = false) => api.get<ListResponse<ProviderInfo>>("/ai/providers", { refresh }),
  models: (params?: { provider?: string; task?: AITaskType }) =>
    api.get<ListResponse<ModelSpec>>("/ai/models", params),
  recommend: (task: AITaskType, provider?: string) =>
    api.get<ModelRecommendation>("/ai/recommend", { task, provider }),
  tasks: () => api.get<ListResponse<TaskInfo>>("/ai/tasks"),
  prompts: (task?: AITaskType) => api.get<ListResponse<PromptInfo>>("/ai/prompts", { task }),
  transcriptionEngines: (refresh = false) =>
    api.get<ListResponse<TranscriptionProviderInfo>>("/ai/transcription/engines", { refresh }),
  ttsProviders: (refresh = false) =>
    api.get<ListResponse<TTSProviderInfo>>("/ai/tts/providers", { refresh }),
  voices: (params?: { provider?: string; language?: Language }) =>
    api.get<ListResponse<VoiceSpec>>("/ai/tts/voices", params),
};

// -- system / settings ---------------------------------------------------

export const systemApi = {
  status: () => api.get<SystemStatus>("/system/status"),
  media: () => api.get<MediaCapabilities>("/system/media"),
  browse: (path?: string) => api.get<BrowseResult>("/system/browse", { path }),
};

export const settingsApi = {
  get: () => api.get<SettingsPayload>("/settings"),
  update: (values: Record<string, unknown>) => api.put<SettingsPayload>("/settings", { values }),
  reset: (key?: string) => api.post<SettingsPayload>("/settings/reset", { key }),
};

export type { AudioPresetInfo };
