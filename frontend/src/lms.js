// Cliente del plano de control (clases, membresías, tareas).
// Todas las llamadas van con el JWT en el header Authorization.
import { authHeaders } from "./auth";

const API = import.meta.env.VITE_API_URL;

async function call(path, method = "GET", body) {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// --- Clases (F2) ---
export const listClasses = () => call("/classes", "GET");
export const createClass = (name) => call("/classes", "POST", { name });
export const deleteClass = (classId) => call("/classes/delete", "POST", { classId });
