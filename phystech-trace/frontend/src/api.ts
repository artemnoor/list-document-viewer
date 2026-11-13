import type { DocumentResult, LinkingResult, StageName, TraceProject } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail : payload?.error ?? response.statusText;
    throw new Error(`${message} (${response.status})`);
  }
  return payload as T;
}

export const api = {
  listProjects: () => request<{ projects: TraceProject[] }>("/api/projects"),
  getProject: (id: string) => request<TraceProject>(`/api/projects/${encodeURIComponent(id)}`),
  createProject: (body: { name: string; data_classification: string; allow_external_llm: boolean }) => request<TraceProject>("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  async upload(id: string, role: "kfz" | "primary", files: File[]) {
    const form = new FormData(); form.set("role", role); files.forEach((file) => form.append("files", file));
    return request(`/api/projects/${encodeURIComponent(id)}/documents`, { method: "POST", body: form });
  },
  process: (id: string) => request(`/api/projects/${encodeURIComponent(id)}/process`, { method: "POST" }),
  retry: (id: string, stage: StageName) => request(`/api/projects/${encodeURIComponent(id)}/retry?stage=${stage}`, { method: "POST" }),
  result: (projectId: string, documentId: string) => request<DocumentResult>(`/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/result`),
  decide: (projectId: string, linkId: string, status: "confirmed" | "rejected") => request<{ linking_result: LinkingResult }>(`/api/projects/${encodeURIComponent(projectId)}/links/${encodeURIComponent(linkId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }),
};

export const services = [
  { name: "Document Parser", kind: "Распознавание", url: "http://localhost:8081/docs" },
  { name: "Structured Extraction", kind: "Извлечение", url: "http://localhost:8082/docs" },
  { name: "Document Linking", kind: "Связи документов", url: "http://localhost:8083/docs" },
  { name: "Gateway API", kind: "Оркестрация", url: "http://localhost:8084/docs" },
];
