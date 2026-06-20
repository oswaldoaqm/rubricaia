// Cliente del plano de control (clases, membresías, tareas).
// Todas las llamadas van con el JWT en el header Authorization.
import { authHeaders, clearToken } from "./auth";

const API = import.meta.env.VITE_API_URL;

async function call(path, method = "GET", body) {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) {
    clearToken();
    window.location.reload();
    return new Promise(() => {});
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// --- Clases (F2) ---
export const listClasses = () => call("/classes", "GET");
export const createClass = (name) => call("/classes", "POST", { name });
export const deleteClass = (classId) => call("/classes/delete", "POST", { classId });

// --- Membresías / invitaciones (F3) ---
export const getClassDetail = (classId) =>
  call(`/classes/detail?classId=${encodeURIComponent(classId)}`, "GET");
export const inviteMember = (classId, email) =>
  call("/classes/invite", "POST", { classId, email });
export const removeMember = (classId, email) =>
  call("/classes/remove", "POST", { classId, email });
export const acceptInvite = (classId) => call("/classes/accept", "POST", { classId });

// --- Tareas (F4) ---
export const createTask = (classId, task) => call("/tasks", "POST", { classId, ...task });
export const updateTask = (classId, taskId, task) =>
  call("/tasks/update", "POST", { classId, taskId, ...task });
export const deleteTask = (classId, taskId) =>
  call("/tasks/delete", "POST", { classId, taskId });

// P2: entregas + resultados de una tarea (vista del profesor).
export const getTaskSubmissions = (classId, taskId) =>
  call(
    `/tasks/submissions?classId=${encodeURIComponent(classId)}&taskId=${encodeURIComponent(taskId)}`,
    "GET"
  );

// G1: historial de intentos del propio alumno en una tarea.
export const getTaskAttempts = (taskId) =>
  call(`/tasks/attempts?taskId=${encodeURIComponent(taskId)}`, "GET");
