// Cliente de la API de RúbricaIA.
// La URL del backend se inyecta en build time con VITE_API_URL (ver deploy-frontend.sh).
const API = import.meta.env.VITE_API_URL;

if (!API) {
  // Aviso util si se buildeo sin la variable.
  console.warn("VITE_API_URL no definida: compila con VITE_API_URL=<API_URL> npm run build");
}

// 1) Pide una presigned URL para subir el CSV.
export async function createUpload(rubrica) {
  const r = await fetch(`${API}/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rubrica }),
  });
  if (!r.ok) throw new Error(`createUpload HTTP ${r.status}`);
  return r.json(); // { jobId, uploadUrl, headers, key }
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
