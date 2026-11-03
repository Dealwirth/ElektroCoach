/**
 * Typen der ElektroCoach-API. Bewusst schlank gehalten, damit die Oberflaeche
 * nur die tatsaechlich verwendeten Felder kennt.
 */

export interface DashboardStats {
  documents: number;
  pages: number;
  chunks: number;
  questions: number;
  attempts: number;
  accuracy: number;
  needs_review_questions: number;
  needs_review_pages: number;
  exams_finished: number;
  best_exam_score: number | null;
  due_reviews: number;
  streak_days: number;
  today_minutes: number;
  daily_goal_minutes: number;
  topics: number;
}

export interface SeriesPoint {
  day: string;
  questions: number;
  accuracy: number;
  minutes: number;
}

export interface Dashboard {
  stats: DashboardStats;
  series: SeriesPoint[];
  weak_areas: Array<{ id: string; name: string; accuracy: number; attempts: number }>;
  due: Array<Record<string, unknown>>;
  topics: Topic[];
  activity: Array<{ kind: string; detail: string; created_at: string }>;
  plan: StudyPlan;
  ai: AiStatus;
}

export interface Topic {
  id: string;
  slug: string;
  name: string;
  description: string;
  parent_id: string | null;
  coverage: number;
  source: string;
  ordering: number;
  chunk_count: number;
  question_count: number;
  mastery: { score: number; level: string };
}

export interface Question {
  id: string;
  topic_id: string | null;
  topic_name?: string | null;
  qtype: string;
  difficulty: number;
  prompt: string;
  options: string[];
  answer: string;
  solution_steps: string;
  explanation: string;
  points: number;
  source_chunk_ids: string[];
  sources?: SourceRef[];
  ai_source: string;
  verified: number;
  needs_review: number;
  attempt_count?: number;
  due_at?: string | null;
  srs_state?: string | null;
  srs?: SrsInfo | null;
}

export interface SrsInfo {
  ease: number;
  interval_days: number;
  repetitions: number;
  lapses: number;
  state: string;
  due_at: string | null;
}

export interface SourceRef {
  id: string;
  page_number: number | null;
  heading: string | null;
  document_id: string;
  filename: string;
  excerpt: string;
}

export interface GradeResult {
  attempt_id: string;
  question_id: string;
  score: number;
  max_points: number;
  correct: boolean;
  partial: boolean;
  feedback: string;
  solution_steps: string;
  reference_answer: string;
  needs_review: boolean;
  ai_used: boolean;
  sources: SourceRef[];
  srs: SrsInfo & { due_at: string };
}

export interface DocumentItem {
  id: string;
  filename: string;
  size_bytes: number;
  page_count: number;
  source: string;
  collection: string | null;
  status: string;
  error: string | null;
  needs_review_count: number;
  created_at: string;
  updated_at: string;
}

export interface PageItem {
  id: string;
  page_number: number;
  text: string;
  ocr_confidence: number | null;
  needs_review: number;
  image_path: string | null;
  meta_json: string;
}

export interface ImportJob {
  id: string;
  status: string;
  total_files: number;
  processed_files: number;
  failed_files: number;
  current_item: string;
  message: string;
  created_at: string;
  updated_at: string;
  results?: Array<Record<string, unknown>>;
  imported?: number;
  duplicates?: number;
  progress_percent?: number;
}

export interface ExamItem {
  id: string;
  name: string;
  duration_minutes: number;
  total_points: number;
  status: string;
  score: number | null;
  passed: number | null;
  pass_probability: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  question_count?: number;
}

export interface ExamQuestion {
  exam_question_id: string;
  ordinal: number;
  points: number;
  answer: string | null;
  score: number | null;
  feedback: string | null;
  question_id: string;
  qtype: string;
  difficulty: number;
  prompt: string;
  options: string[];
  base_points: number;
  topic_name: string | null;
}

export interface Exam extends ExamItem {
  questions: ExamQuestion[];
  elapsed_seconds?: number | null;
  session_id?: string;
}

export interface ExamResult {
  exam_id: string;
  name: string;
  achieved: number;
  total: number;
  percentage: number;
  passed: boolean;
  pass_probability: number;
  results: Array<{
    question_id: string;
    qtype: string;
    topic: string | null;
    points: number;
    achieved: number;
    feedback: string;
  }>;
  weak_topics: Array<{ topic: string; accuracy: number; points: number }>;
}

export interface SymbolPin {
  id: string;
  x: number;
  y: number;
  name: string;
}

export interface SymbolDef {
  type: string;
  category: string;
  name: string;
  width: number;
  height: number;
  pins: SymbolPin[];
}

export interface Component {
  id: string;
  type: string;
  x: number;
  y: number;
  rotation: number;
  label: string;
  props?: Record<string, unknown>;
}

export interface Wire {
  id: string;
  from: { component_id: string; pin_id: string };
  to: { component_id: string; pin_id: string };
  points: Array<{ x: number; y: number }>;
  color?: string;
}

export interface Junction {
  id: string;
  x: number;
  y: number;
}

export interface DesignData {
  components: Component[];
  wires: Wire[];
  junctions: Junction[];
  grid?: number;
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  free_pins: Array<{ component_id: string; pin_id: string; x: number; y: number; name: string }>;
  component_count: number;
  wire_count: number;
  junction_count: number;
}

export interface SchematicProject {
  id: string;
  name: string;
  description: string;
  grid: number;
  created_at: string;
  updated_at: string;
  data?: DesignData;
  validation?: ValidationResult;
  stats?: {
    components: number;
    wires: number;
    by_type: Record<string, number>;
    wire_length_px: number;
    wire_length_m: number;
  };
}

export interface AiStatus {
  mode: string;
  any_available: boolean;
  ollama: {
    available: boolean;
    reason?: string;
    model?: string;
    models?: string[];
    recommended?: Array<{ name: string; size_gb: number; note: string }>;
  };
  gemini: {
    available: boolean;
    reason?: string;
    quota?: { used: number; limit: number; remaining: number | null; exhausted: boolean };
    text_model?: string;
    vision_model?: string;
    free_tier_candidates?: string[];
  };
}

export interface OllamaAddonStatus {
  supervisor: boolean;
  installed: boolean;
  state?: string | null;
  slug?: string | null;
  url?: string;
  suggested_url?: string;
  error?: string;
}

export interface OllamaAddonEnsure {
  ok: boolean;
  slug?: string;
  url?: string;
  installed?: boolean;
  started?: boolean;
  created?: boolean;
  reachable?: boolean;
  state?: string | null;
  error?: string | null;
}

export interface RefineJob {
  id: string;
  document_id?: string | null;
  scope: string;
  status: string;
  total_pages: number;
  processed_pages: number;
  current_page: number;
  message: string;
  progress_percent?: number;
  created_at: string;
  updated_at: string;
}

export interface RefineResult {
  ok: boolean;
  page_id?: string;
  document_id?: string;
  original?: string;
  text?: string;
  confidence?: number | null;
  needs_review?: boolean;
  notes?: string;
  providers?: string[];
  error?: string;
}

export interface StorageReport {
  disk_total_mb: number;
  disk_used_mb: number;
  disk_free_mb: number;
  disk_free_percent: number;
  database_mb: number;
  wal_mb: number;
  documents_mb: number;
  pages_mb: number;
  backups_mb: number;
  counts: Record<string, number>;
  memory_available_mb: number | null;
  load_1min: number | null;
  low_space_warning: boolean;
  integrity: string;
}

export interface StudyPlan {
  minutes_available: number;
  due_total: number;
  schedule: {
    reviews: Array<Record<string, unknown>>;
    new_items: Array<Record<string, unknown>>;
    review_count: number;
    new_count: number;
    planned_minutes: number;
  };
  weak_topics: Array<{ id: string; name: string; accuracy: number; attempts: number }>;
  goals: Goal[];
  streak: number;
  today_minutes: number;
}

export interface Goal {
  id: string;
  title: string;
  topic_id: string | null;
  topic_name?: string | null;
  target: string;
  due_date: string | null;
  progress: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface HaStatus {
  mqtt_enabled: boolean;
  mqtt_host: string;
  mqtt_connected: boolean;
  supervisor_token: boolean;
  notify_service: string | null;
  sensor_update_interval: number;
  scheduler_running: boolean;
  sensors: {
    progress_percent: number;
    today_minutes: number;
    due_reviews: number;
    questions: number;
    accuracy: number;
    streak_days: number;
    best_exam_score: number | null;
    free_space_mb: number;
    status_text: string;
    documents: number;
    needs_review_pages: number;
  };
}

export interface BackupItem {
  name: string;
  size_bytes: number;
  size_mb: number;
  created_at: string;
}

export interface SystemInfo {
  version: string;
  python: string;
  platform: string;
  machine: string;
  uptime_seconds: number;
  cpu_count: number | null;
  load_1min: number | null;
  memory_available_mb: number | null;
  import_queue: number;
  import_worker_alive: boolean;
  storage: StorageReport;
  ai: AiStatus;
  ha: { mqtt_enabled: boolean; sensor_update_interval: number };
  tesseract: { available: boolean; languages: string[]; configured: string };
}
