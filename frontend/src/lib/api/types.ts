/**
 * API types, hand-mirrored from the backend's Pydantic models.
 *
 * There is no authentication here (see docs/ARCHITECTURE.md) - every type
 * below corresponds 1:1 to a domain model or schema in `backend/app/domain`
 * and `backend/app/api/schemas`. Keep them in sync when the backend changes;
 * a mismatch surfaces immediately as a type error at the call site.
 */

// -- enums, mirrored from app/domain/enums.py --------------------------------

export type ProjectStatus = "draft" | "active" | "completed" | "archived";

export type AssetType =
  | "video"
  | "audio"
  | "transcript"
  | "subtitle"
  | "voice"
  | "rendered_video";

export type DocumentType =
  | "transcript_raw"
  | "transcript_refined"
  | "edited"
  | "translation"
  | "speech_script"
  | "note";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type JobType =
  | "audio_extract"
  | "transcribe"
  | "text_task"
  | "subtitle_generate"
  | "subtitle_sync"
  | "subtitle_render"
  | "tts_synthesize";

export type AITaskType =
  | "transcription_refinement"
  | "text_editing"
  | "translation"
  | "text_analysis"
  | "subtitle_processing"
  | "summarization"
  | "general";

export type Language = "fa" | "en";

export type SubtitleFormat = "srt" | "vtt" | "ass";
export type SubtitleAlignment = "left" | "center" | "right";
export type SubtitlePosition = "top" | "middle" | "bottom";
export type SubtitleSegmentationMode =
  | "sentence"
  | "automatic"
  | "short"
  | "normal"
  | "custom";

/** How a whole track is retimed in one batch operation. */
export type SubtitleRetimeMode = "shift" | "scale" | "reading_speed" | "stretch";

/** Where a track's current timings came from, and therefore how much to trust them. */
export type SubtitleTimingSource =
  | "asr_segments"
  | "estimated"
  | "audio_aligned"
  | "speech_distributed"
  | "manual";

/** Which placement strategy the audio synchronisation job should use. */
export type SubtitleSyncStrategy = "auto" | "align" | "distribute";

export type VoiceGender = "male" | "female" | "unknown";
export type VoiceAge = "young" | "adult" | "mature" | "unknown";
export type SpeakingStyle =
  | "friendly"
  | "casual"
  | "professional"
  | "formal"
  | "energetic"
  | "calm"
  | "neutral";
export type SpeechSegmentKind = "text" | "pause";

// -- entities ------------------------------------------------------------

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  asset_count: number;
  document_count: number;
  active_job_count: number;
}

export interface MediaProbe {
  duration_seconds: number | null;
  format_name: string;
  size_bytes: number;
  bit_rate: number | null;
  has_video: boolean;
  has_audio: boolean;
  video_codec: string | null;
  audio_codec: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  sample_rate: number | null;
  channels: number | null;
}

export interface MediaAsset {
  id: string;
  project_id: string;
  type: AssetType;
  original_filename: string;
  path: string;
  size_bytes: number;
  format: string;
  duration_seconds: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TextDocument {
  id: string;
  project_id: string;
  type: DocumentType;
  title: string;
  content: string;
  language: Language;
  version: number;
  source_document_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobLogLine {
  ts: number;
  stream: "stdout" | "stderr" | "system";
  text: string;
}

export interface Job {
  id: string;
  project_id: string | null;
  type: JobType;
  status: JobStatus;
  progress: number | null;
  stage: string;
  provider: string | null;
  model: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SubtitleStyle {
  font_family: string;
  font_size: number;
  bold: boolean;
  italic: boolean;
  text_color: string;
  background_color: string;
  background_opacity: number;
  outline_color: string;
  outline_width: number;
  shadow_depth: number;
  position: SubtitlePosition;
  alignment: SubtitleAlignment;
  margin_vertical: number;
  margin_horizontal: number;
}

export interface SubtitleCue {
  id: string;
  track_id: string;
  index: number;
  start: number;
  end: number;
  text: string;
  style_overrides: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

/** What a retime or a synchronisation actually changed. */
export interface RetimeReport {
  mode: string;
  cue_count: number;
  changed_count: number;
  overlaps_fixed: number;
  durations_adjusted: number;
  clamped_count: number;
  max_shift_seconds: number;
  first_start: number;
  last_end: number;
}

export interface RetimeResponse {
  items: SubtitleCue[];
  total: number;
  report: RetimeReport;
}

export interface SubtitleTrack {
  id: string;
  project_id: string;
  name: string;
  language: Language;
  style: SubtitleStyle;
  source_document_id: string | null;
  created_at: string;
  updated_at: string;
  cues: SubtitleCue[];
}

// -- AI layer --------------------------------------------------------------

export interface ModelSpec {
  id: string;
  provider: string;
  display_name: string;
  tier: "fast" | "balanced" | "powerful";
  good_for: AITaskType[];
  rationale_fa: string;
  speed: number;
  quality: number;
  context_note: string;
  available: boolean;
}

export interface ModelRecommendation {
  task: AITaskType;
  provider: string;
  recommended_model: string;
  reason_fa: string;
  alternatives: ModelSpec[];
  from_user_preference: boolean;
}

export interface ProviderInfo {
  id: string;
  display_name: string;
  available: boolean;
  unavailable_reason: string | null;
  version: string | null;
  executable_path: string | null;
  capabilities: string[];
  supported_tasks: AITaskType[];
  models: ModelSpec[];
}

export interface TaskInfo {
  id: AITaskType;
  label_fa: string;
  description_fa: string;
  preferred_tier: string;
  max_input_chars: number;
}

export interface PromptInfo {
  id: string;
  name_fa: string;
  task: AITaskType;
  category: string;
  description_fa: string;
  body: string;
  variables: string[];
  is_builtin: boolean;
}

export interface EngineModel {
  id: string;
  label_fa: string;
  size_mb: number;
  description_fa: string;
  downloaded: boolean;
  recommended: boolean;
}

export interface TranscriptionProviderInfo {
  id: string;
  display_name: string;
  available: boolean;
  unavailable_reason: string | null;
  hint: string | null;
  version: string | null;
  offline: boolean;
  supported_languages: Language[];
  models: EngineModel[];
  provides_word_timings: boolean;
}

export interface VoiceSpec {
  id: string;
  provider: string;
  name: string;
  language: Language;
  /** Full BCP-47 tag, e.g. "en-GB" - the accent, which `language` cannot express. */
  locale: string;
  gender: VoiceGender;
  age: VoiceAge;
  styles: SpeakingStyle[];
  supports_pitch: boolean;
  supports_rate: boolean;
  description: string;
  /** A sample the provider hosts itself, when it publishes one. */
  preview_url: string | null;
}

export interface TTSProviderInfo {
  id: string;
  display_name: string;
  available: boolean;
  unavailable_reason: string | null;
  hint: string | null;
  offline: boolean;
  supports_pitch: boolean;
  supports_styles: boolean;
  supported_languages: Language[];
  voice_count: number;
  pricing: "free" | "freemium" | "paid";
  /** True when this provider needs a key before it can do anything at all. */
  requires_api_key: boolean;
  /** Settings key holding that key, so the UI can point straight at it. */
  api_key_setting: string | null;
}

// -- system / settings -------------------------------------------------

export interface DependencyStatus {
  id: string;
  label_fa: string;
  available: boolean;
  required: boolean;
  version: string | null;
  path: string | null;
  detail_fa: string | null;
  hint_fa: string | null;
}

export interface SystemStatus {
  ready: boolean;
  app_version: string;
  python_version: string;
  platform: string;
  dependencies: DependencyStatus[];
  workspace_path: string;
  database_path: string;
  active_jobs: number;
  queued_jobs: number;
}

export interface AudioPresetInfo {
  id: string;
  label_fa: string;
  extension: string;
  approx_mb_per_hour: number;
  description_fa: string;
  sample_rate: number | null;
}

export interface RenderQualityInfo {
  id: string;
  label_fa: string;
  description_fa: string;
  crf: number;
}

export interface MediaCapabilities {
  audio_presets: AudioPresetInfo[];
  render_qualities: RenderQualityInfo[];
  ffmpeg_available: boolean;
  ffmpeg_version: string | null;
}

export interface SettingsPayload {
  values: Record<string, unknown>;
  grouped: Record<string, Record<string, unknown>>;
  defaults: Record<string, unknown>;
}

export interface BrowseEntry {
  name: string;
  path: string;
  type: "drive" | "directory" | "file";
  size?: number;
  extension?: string;
}

export interface BrowseResult {
  current: string | null;
  parent: string | null;
  entries: BrowseEntry[];
}

// -- generic wrappers -----------------------------------------------------

export interface ListResponse<T> {
  items: T[];
  total: number;
}

export interface JobAcceptedResponse {
  job: Job;
  message: string;
}

export interface OperationResponse {
  ok: boolean;
  message: string;
}

export interface ImportedAssetResponse {
  asset: MediaAsset;
  probe: MediaProbe | null;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    hint?: string;
    details?: Record<string, unknown>;
  };
}
