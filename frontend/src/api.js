// Cliente de la API de RúbricaIA.
// La URL del backend se inyecta en build time con VITE_API_URL (ver deploy-frontend.sh).
import { authHeaders, clearToken } from "./auth";

const API = import.meta.env.VITE_API_URL;

if (!API) {
  console.warn("VITE_API_URL no definida: compila con VITE_API_URL=<API_URL> npm run build");
}

// Crea una entrega ligada a una tarea: la rúbrica/pesos los pone el backend desde
// la tarea; va autenticada con el JWT del estudiante.
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

// Sube el archivo CSV directo a S3 con los headers que firmó el backend.
export async function uploadCsv(uploadUrl, headers, file) {
  const r = await fetch(uploadUrl, { method: "PUT", headers, body: file });
  if (!r.ok) throw new Error(`uploadCsv HTTP ${r.status}`);
}

// Consulta estado + resultados de un job (la vista de resultado del alumno la usa).
export async function getJob(jobId) {
  const r = await fetch(`${API}/jobs/${jobId}`);
  if (!r.ok) throw new Error(`getJob HTTP ${r.status}`);
  return r.json();
}
