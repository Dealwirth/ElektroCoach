/**
 * API-Client.
 *
 * Der Basispfad kommt aus basePath.ts. Hinter dem Home-Assistant-Ingress ist
 * das der wechselnde Pfad /api/hassio_ingress/<token>, bei direktem Aufruf
 * (Docker, Tests) bleibt er leer. Dadurch funktionieren alle Aufrufe auch auf
 * verschachtelten Seiten und nach einem Neuladen.
 */

import { apiBase } from "./basePath";

const BASE = apiBase;

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

function describeDetail(detail: unknown): string {
  if (!detail) return "Unbekannter Fehler";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
      .join(", ");
  }
  if (typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    if (typeof obj.message === "string") return obj.message;
    if (typeof obj.detail === "string") return obj.detail;
    return JSON.stringify(obj);
  }
  return String(detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/${path.replace(/^\//, "")}`, {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (error) {
    throw new ApiError(0, `Keine Verbindung zum Server: ${String(error)}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail ?? payload;
    throw new ApiError(response.status, describeDetail(detail));
  }
  return payload as T;
}

function query(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<{ status: string; version: string }>("health"),
  systemInfo: () => request<import("./types").SystemInfo>("system/info"),
  dashboard: () => request<import("./types").Dashboard>("dashboard"),
  settings: () => request<Record<string, unknown>>("settings"),
  updateSettings: (values: Record<string, unknown>) =>
    request<{ ok: boolean; changed: string[] }>("settings", {
      method: "PUT",
      body: JSON.stringify({ values }),
    }),
  search: (q: string, limit = 25) =>
    request<{ query: string; count: number; results: Array<Record<string, unknown>> }>(
      `search${query({ q, limit })}`,
    ),

  // Import
  importFormats: () => request<Record<string, unknown>>("import/formats"),
  importJobs: (limit = 10) =>
    request<{ items: import("./types").ImportJob[]; queue: number }>(
      `import/jobs${query({ limit })}`,
    ),
  importJob: (id: string) => request<import("./types").ImportJob>(`import/jobs/${id}`),
  cancelJob: (id: string) =>
    request<{ ok: boolean }>(`import/jobs/${id}/cancel`, { method: "POST" }),
  upload: async (files: File[], collection?: string) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    if (collection) form.append("collection", collection);
    const response = await fetch(`${BASE}/import`, { method: "POST", body: form });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = (payload as { detail?: unknown } | null)?.detail ?? payload;
      throw new ApiError(response.status, describeDetail(detail));
    }
    return payload as {
      ok: boolean;
      job_id: string;
      accepted: number;
      rejected: Array<{ filename: string; error: string }>;
      message: string;
    };
  },

  // Dokumente
  documents: (params: Record<string, unknown> = {}) =>
    request<{ total: number; items: import("./types").DocumentItem[] }>(
      `documents${query(params)}`,
    ),
  document: (id: string) =>
    request<import("./types").DocumentItem & { pages: import("./types").PageItem[] }>(
      `documents/${id}`,
    ),
  documentChunks: (id: string) =>
    request<{ items: Array<Record<string, unknown>> }>(`documents/${id}/chunks`),
  deleteDocument: (id: string) =>
    request<{ ok: boolean }>(`documents/${id}`, { method: "DELETE" }),
  collections: () =>
    request<{ items: Array<{ name: string; n: number }> }>("documents/collections"),
  updatePageText: (pageId: string, text: string, clearReview = true) =>
    request<{ ok: boolean }>(`pages/${pageId}/text`, {
      method: "PUT",
      body: JSON.stringify({ text, clear_review: clearReview }),
    }),
  pageImageUrl: (pageId: string) => `${BASE}/pages/${pageId}/image`,
  reviewPages: (limit = 100) =>
    request<{ items: Array<Record<string, unknown>>; count: number }>(
      `review/pages${query({ limit })}`,
    ),

  // Lernsystem
  topics: () => request<{ items: import("./types").Topic[] }>("topics"),
  analyzeTopics: (useAi = true) =>
    request<Record<string, unknown>>("topics/analyze", {
      method: "POST",
      body: JSON.stringify({ use_ai: useAi }),
    }),
  missingTopics: () =>
    request<{ items: Array<{ id: string; slug: string; name: string; chunks: number }> }>(
      "topics/missing",
    ),
  generateQuestions: (payload: Record<string, unknown>) =>
    request<{
      created: number;
      ai_used: boolean;
      note: string | null;
      topic_name: string;
      questions: import("./types").Question[];
    }>("questions/generate", { method: "POST", body: JSON.stringify(payload) }),
  questions: (params: Record<string, unknown> = {}) =>
    request<{ total: number; items: import("./types").Question[] }>(
      `questions${query(params)}`,
    ),
  question: (id: string) => request<import("./types").Question>(`questions/${id}`),
  deleteQuestion: (id: string) =>
    request<{ ok: boolean }>(`questions/${id}`, { method: "DELETE" }),
  answerQuestion: (id: string, payload: Record<string, unknown>) =>
    request<import("./types").GradeResult>(`questions/${id}/answer`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  dueQuestions: (limit = 50) =>
    request<{ items: Array<Record<string, unknown>>; count: number }>(
      `review/due${query({ limit })}`,
    ),
  plan: (minutes?: number) =>
    request<import("./types").StudyPlan>(`plan${query({ minutes })}`),
  progress: () => request<Record<string, unknown>>("progress"),
  goals: () => request<{ items: import("./types").Goal[] }>("goals"),
  createGoal: (payload: Record<string, unknown>) =>
    request<import("./types").Goal>("goals", { method: "POST", body: JSON.stringify(payload) }),
  updateGoal: (id: string, payload: Record<string, unknown>) =>
    request<{ ok: boolean }>(`goals/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteGoal: (id: string) => request<{ ok: boolean }>(`goals/${id}`, { method: "DELETE" }),

  // Pruefungen
  examPresets: () =>
    request<{ presets: Record<string, { name: string; minutes: number; questions: number; points: number }> }>(
      "exams/presets",
    ),
  exams: (limit = 30) =>
    request<{ items: import("./types").ExamItem[] }>(`exams${query({ limit })}`),
  exam: (id: string) => request<import("./types").Exam>(`exams/${id}`),
  createExam: (payload: Record<string, unknown>) =>
    request<{ ok: boolean; exam: import("./types").Exam }>("exams", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startExam: (id: string) =>
    request<import("./types").Exam>(`exams/${id}/start`, { method: "POST" }),
  saveExamAnswer: (id: string, questionId: string, answer: string) =>
    request<{ ok: boolean }>(`exams/${id}/answer`, {
      method: "PUT",
      body: JSON.stringify({ question_id: questionId, answer }),
    }),
  finishExam: (id: string, sessionId?: string, useAi = true) =>
    request<import("./types").ExamResult>(`exams/${id}/finish`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId ?? null, use_ai: useAi }),
    }),
  handwritingStatus: () =>
    request<{ available: boolean; images_allowed: boolean; gemini_configured: boolean }>(
      "handwriting/status",
    ),
  transcribeHandwriting: (
    examId: string,
    questionId: string,
    image: string,
    browserText = "",
    save = true,
  ) =>
    request<{
      ok: boolean;
      text?: string;
      error?: string;
      hint?: string;
      method?: string;
      confidence?: number | null;
      unleserlich?: boolean;
      hinweis?: string;
      saved?: boolean;
    }>(`exams/${examId}/handwriting`, {
      method: "POST",
      body: JSON.stringify({
        question_id: questionId,
        image,
        browser_text: browserText,
        save,
      }),
    }),
  compareExams: () => request<Record<string, unknown>>("exams/compare"),
  deleteExam: (id: string) => request<{ ok: boolean }>(`exams/${id}`, { method: "DELETE" }),

  // Schaltplan
  schematicLibrary: () =>
    request<{ grid: number; symbols: import("./types").SymbolDef[]; categories: Record<string, import("./types").SymbolDef[]> }>(
      "schematic/library",
    ),
  schematicProjects: () =>
    request<{ items: import("./types").SchematicProject[] }>("schematic/projects"),
  schematicProject: (id: string) =>
    request<import("./types").SchematicProject>(`schematic/projects/${id}`),
  createSchematic: (payload: Record<string, unknown>) =>
    request<import("./types").SchematicProject>("schematic/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  saveSchematic: (id: string, payload: Record<string, unknown>) =>
    request<import("./types").SchematicProject>(`schematic/projects/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteSchematic: (id: string) =>
    request<{ ok: boolean }>(`schematic/projects/${id}`, { method: "DELETE" }),
  duplicateSchematic: (id: string) =>
    request<import("./types").SchematicProject>(`schematic/projects/${id}/duplicate`, {
      method: "POST",
    }),
  validateSchematic: (data: import("./types").DesignData) =>
    request<import("./types").ValidationResult>("schematic/validate", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  analyzeSchematic: (data: import("./types").DesignData) =>
    request<{
      validation: import("./types").ValidationResult;
      stats: import("./types").SchematicProject["stats"];
      networks: string[][];
    }>("schematic/analyze", { method: "POST", body: JSON.stringify(data) }),
  schematicSvgUrl: (id: string) => `${BASE}/schematic/projects/${id}/export.svg`,
  schematicJsonUrl: (id: string) => `${BASE}/schematic/projects/${id}/export.json`,

  // KI
  aiStatus: () => request<import("./types").AiStatus>("ai/status"),
  aiUsage: () => request<Record<string, unknown>>("ai/usage"),
  ollamaModels: () => request<Record<string, unknown>>("ai/ollama/models"),
  geminiModels: () => request<Record<string, unknown>>("ai/gemini/models"),
  ollamaAddon: () => request<import("./types").OllamaAddonStatus>("ai/ollama/addon"),
  ollamaAddonEnsure: () =>
    request<import("./types").OllamaAddonEnsure>("ai/ollama/addon/ensure", { method: "POST" }),
  ollamaPull: (model: string) =>
    request<{ ok: boolean; model: string }>("ai/ollama/pull", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  ollamaInstalled: () =>
    request<{ ok: boolean; models: string[]; url?: string; error?: string }>("ai/ollama/installed"),
  chat: (message: string, useLibrary = true, provider = "auto", web = "auto") =>
    request<{
      ok: boolean;
      answer?: string;
      error?: string;
      hint?: string;
      provider?: string;
      model?: string;
      requested?: string;
      external?: boolean;
      fallback_used?: boolean;
      web_used?: boolean;
      sources: Array<Record<string, unknown>>;
      web_sources?: Array<{ title: string; url: string; kind?: string }>;
    }>("ai/chat", {
      method: "POST",
      body: JSON.stringify({ message, use_library: useLibrary, provider, web }),
    }),
  explain: (question: string, topicId?: string, level = "pruefung") =>
    request<{ ok: boolean; answer?: string; error?: string; provider?: string }>("ai/explain", {
      method: "POST",
      body: JSON.stringify({ question, topic_id: topicId ?? null, level }),
    }),
  aiHandwritingStatus: () =>
    request<{ available: boolean; images_allowed: boolean; gemini_configured: boolean }>(
      "ai/handwriting/status",
    ),
  aiTranscribe: (image: string, hint = "", browserText = "") =>
    request<{
      ok: boolean;
      text?: string;
      error?: string;
      hint?: string;
      method?: string;
      confidence?: number | null;
      unleserlich?: boolean;
      hinweis?: string;
    }>("ai/handwriting", {
      method: "POST",
      body: JSON.stringify({ image, hint, browser_text: browserText }),
    }),

  // KI-Nachbearbeitung erkannter Texte
  startRefine: (documentId?: string | null, scope: "review" | "document" = "review") =>
    request<{ ok: boolean; job_id: string; scope: string }>("ai/refine", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId ?? null, scope }),
    }),
  refineJobs: (limit = 10) =>
    request<{ items: import("./types").RefineJob[]; queue: number }>(
      `ai/refine/jobs${query({ limit })}`,
    ),
  refineJob: (id: string) => request<import("./types").RefineJob>(`ai/refine/jobs/${id}`),
  cancelRefine: (id: string) =>
    request<{ ok: boolean }>(`ai/refine/jobs/${id}/cancel`, { method: "POST" }),
  refinePage: (pageId: string) =>
    request<import("./types").RefineResult>("ai/refine/page", {
      method: "POST",
      body: JSON.stringify({ page_id: pageId }),
    }),

  // Home Assistant
  haStatus: () => request<import("./types").HaStatus>("ha/status"),
  haPublish: () => request<{ ok: boolean }>("ha/publish", { method: "POST" }),
  haNotify: (message: string, title = "ElektroCoach") =>
    request<{ ok: boolean }>("ha/notify", {
      method: "POST",
      body: JSON.stringify({ message, title }),
    }),
  haNotifyDue: () => request<{ ok: boolean }>("ha/notify/due", { method: "POST" }),

  // Backup
  backups: () => request<{ items: import("./types").BackupItem[] }>("backups"),
  createBackup: (label: string, includeDocuments = true) =>
    request<{ ok: boolean; name: string; size_mb: number }>("backups", {
      method: "POST",
      body: JSON.stringify({ label, include_documents: includeDocuments }),
    }),
  deleteBackup: (name: string) =>
    request<{ ok: boolean }>(`backups/${encodeURIComponent(name)}`, { method: "DELETE" }),
  restoreBackup: (name: string, restoreDocuments = true) =>
    request<{ ok: boolean; restart_required: boolean }>("backups/restore", {
      method: "POST",
      body: JSON.stringify({ name, restore_documents: restoreDocuments }),
    }),
  storage: () => request<import("./types").StorageReport>("storage"),
  maintenance: () =>
    request<{ ok: boolean; integrity: string; size_before_mb: number; size_after_mb: number }>(
      "maintenance",
      { method: "POST" },
    ),
  cleanupUploads: () => request<{ ok: boolean; removed: number }>("documents/cleanup", { method: "POST" }),
};

export { describeDetail };
