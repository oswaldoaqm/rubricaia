// Cliente de autenticación (plano de control multi-tenant).
// Guarda el JWT en localStorage y expone helpers para login/signup y para
// adjuntar el header Authorization en las llamadas protegidas.
const API = import.meta.env.VITE_API_URL;
const KEY = "rubricaia_token";

export function getToken() {
  return localStorage.getItem(KEY);
}
export function setToken(t) {
  localStorage.setItem(KEY, t);
}
export function clearToken() {
  localStorage.removeItem(KEY);
}

// Decodifica el payload del JWT (sin verificar firma: eso lo hace el backend).
export function currentUser() {
  const t = getToken();
  if (!t) return null;
  try {
    const part = t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(decodeURIComponent(escape(atob(part))));
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      clearToken();
      return null;
    }
    return payload; // { email, role, name, ... }
  } catch {
    clearToken();
    return null;
  }
}

export function authHeaders() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function post(path, body) {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

export async function signup(email, password, name) {
  const data = await post("/auth/signup", { email, password, name });
  setToken(data.token);
  return data.user;
}

export async function login(email, password) {
  const data = await post("/auth/login", { email, password });
  setToken(data.token);
  return data.user;
}
