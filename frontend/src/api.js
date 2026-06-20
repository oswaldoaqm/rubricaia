// Cliente de la API de RúbricaIA.
// La URL del backend se inyecta en build time con VITE_API_URL (ver deploy-frontend.sh).
import { authHeaders, clearToken } from "./auth";

const API = import.meta.env.VITE_API_URL;

if (!API) {
  // Aviso util si se buildeo sin la variable.
  console.warn("VITE_API_URL no definida: compila con VITE_API_URL=<API_URL> npm run build");
}

// 1) Pide una presigned URL para subir el CSV.
// pesos: array opcional de números (uno por criterio) para cumplimiento ponderado (F5).
export async function createUpload(rubrica, pesos) {
  const body = { rubrica };
  if (pesos && pesos.length) body.pesos = pesos;
  const r = await fetch(`${API}/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`createUpload HTTP ${r.status}`);
  return r.json(); // { jobId, uploadUrl, headers, key }
}

// 1b) Crea una entrega LIGADA A UNA TAREA (F5). La rúbrica/pesos los pone el
// backend desde la tarea; va autenticada con el JWT del estudiante.
export async function createTaskUpload(classId, taskId) {
  const r = await fetch(`${API}/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ classId, taskId }),
  });
  if (r.status === 401) {
    clearToken();
    window.location.reload();
    return new Promise(() => {});
  }
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.error || `createTaskUpload HTTP ${r.status}`);
  }
  return r.json();
}

// 2) Sube el archivo CSV directo a S3 con los headers que firmo el backend.
export async function uploadCsv(uploadUrl, headers, file) {
  const r = await fetch(uploadUrl, { method: "PUT", headers, body: file });
  if (!r.ok) throw new Error(`uploadCsv HTTP ${r.status}`);
}

// 3) Consulta estado + resultados de un job.
export async function getJob(jobId) {
  const r = await fetch(`${API}/jobs/${jobId}`);
  if (!r.ok) throw new Error(`getJob HTTP ${r.status}`);
  return r.json();
}

// 4) Pide la presigned URL del reporte de clase (Fase 3B). format: html|csv|json.
export async function getReport(jobId, format = "html") {
  const r = await fetch(`${API}/jobs/${jobId}/report?format=${format}`);
  if (!r.ok) throw new Error(`getReport HTTP ${r.status}`);
  return r.json(); // { ready, format, url }
}

// 5) Reprocesa los entregables en FAILED del job (F1).
export async function retryFailed(jobId) {
  const r = await fetch(`${API}/jobs/${jobId}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`retryFailed HTTP ${r.status}`);
  return r.json(); // { requeued }
}
