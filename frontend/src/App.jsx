import { useState, useEffect, useRef } from "react";
import { createTaskUpload, uploadCsv, getJob } from "./api";
import { filesToRows, rowsToCsv } from "./extract";
import { currentUser, login, signup, clearToken } from "./auth";
import {
  listClasses,
  createClass,
  deleteClass,
  getClassDetail,
  inviteMember,
  removeMember,
  acceptInvite,
  createTask,
  updateTask,
  deleteTask,
  getTaskSubmissions,
} from "./lms";

const DEFAULT_RUBRICA = `1) Define un problema real y concreto.
2) Identifica al usuario afectado.
3) Describe el caso de uso.
4) Justifica el impacto esperado con metricas.
5) Redaccion clara y estructurada.`;

const STATUS_LABEL = {
  PENDING: "En cola",
  PROCESSING: "Procesando",
  DONE: "Listo",
  RETRYING: "Reintentando",
  FAILED: "Error",
};

function dueState(dueDate) {
  if (!dueDate) return null;
  const due = new Date(dueDate + "T23:59:59");
  if (Number.isNaN(due.getTime())) return { label: "Entrega: " + dueDate };
  const days = Math.ceil((due - new Date()) / 86400000);
  if (days < 0) return { label: `Vencida hace ${-days} día${-days > 1 ? "s" : ""}`, tone: "overdue" };
  if (days === 0) return { label: "Vence hoy", tone: "soon" };
  if (days <= 3) return { label: `Vence en ${days} día${days > 1 ? "s" : ""}`, tone: "soon" };
  return { label: "Entrega: " + dueDate };
}

function DueLabel({ dueDate }) {
  const s = dueState(dueDate);
  if (!s) return <span className="muted small">Sin fecha límite</span>;
  return <span className={"due" + (s.tone ? " " + s.tone : "")}>{s.label}</span>;
}

function BrandMark() {
  return (
    <svg className="logomark" width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true">
      <rect x="1.5" y="1.5" width="27" height="27" rx="8" fill="#1f4d3a" />
      <path d="M8 11h9M8 15h6" stroke="#f3eee2" strokeWidth="1.7" strokeLinecap="round" opacity="0.5" />
      <path
        d="M8 20.3l3.2 3 7-8.6"
        stroke="#f3eee2"
        strokeWidth="2.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function App() {
  const [user, setUser] = useState(currentUser());

  if (!user) {
    return <AuthScreen onAuth={() => setUser(currentUser())} />;
  }

  function logout() {
    clearToken();
    setUser(null);
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrandMark /> RúbricaIA
        </div>
        <div className="userbox">
          <span className="tag">{user.name || user.email}</span>
          <span className={"rolechip " + user.role}>{user.role}</span>
          <button className="btn link" onClick={logout}>
            salir
          </button>
        </div>
      </header>

      {user.role === "profesor" ? <TeacherClasses /> : <StudentArea />}

      <footer className="foot">
        Arquitectura serverless basada en eventos · S3 → SQS → Lambda → Groq → EventBridge → SNS · AWS Learner Lab
      </footer>
    </div>
  );
}

// Área del estudiante (F3): invitaciones + clases activas. La subida por tarea
// se conecta en F5.
function StudentArea() {
  const [data, setData] = useState(null); // { classes, invitations }
  const [error, setError] = useState(null);
  const [openClass, setOpenClass] = useState(null);

  async function load() {
    try {
      setData(await listClasses());
    } catch (e) {
      setError(e.message);
      setData({ classes: [], invitations: [] });
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onAccept(classId) {
    setError(null);
    try {
      await acceptInvite(classId);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (openClass) {
    return <StudentClassDetail classId={openClass} onBack={() => setOpenClass(null)} />;
  }

  return (
    <main className="card">
      <h2>Mis clases</h2>
      {error && <div className="error">{error}</div>}
      {data === null ? (
        <p className="muted">Cargando…</p>
      ) : (
        <>
          {data.invitations && data.invitations.length > 0 && (
            <div className="invites">
              <div className="ilabel">Invitaciones pendientes</div>
              {data.invitations.map((inv) => (
                <div key={inv.classId} className="inviteitem">
                  <span>
                    Te invitaron a <strong>{inv.name}</strong>
                  </span>
                  <button className="btn small" onClick={() => onAccept(inv.classId)}>
                    Aceptar
                  </button>
                </div>
              ))}
            </div>
          )}
          {data.classes.length === 0 ? (
            <p className="muted">
              Aún no perteneces a ninguna clase. Cuando un profesor te invite, aparecerá aquí
              y la verás tras aceptar.
            </p>
          ) : (
            <ul className="classlist">
              {data.classes.map((c) => (
                <li
                  key={c.classId}
                  className="classitem clickable"
                  onClick={() => setOpenClass(c.classId)}
                >
                  <div>
                    <div className="classname">{c.name}</div>
                    <div className="muted small">{c.ownerEmail}</div>
                  </div>
                  <span className="muted">Abrir →</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  );
}

function StudentClassDetail({ classId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [openTask, setOpenTask] = useState(null);

  function load() {
    getClassDetail(classId).then(setDetail).catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, [classId]);

  if (openTask) {
    return (
      <TaskSubmit
        classId={classId}
        task={openTask}
        onBack={() => {
          setOpenTask(null);
          load();
        }}
      />
    );
  }

  return (
    <main className="card">
      <button className="btn ghost" onClick={onBack}>
        ← Volver
      </button>
      {error && <div className="error">{error}</div>}
      {!detail ? (
        <p className="muted">Cargando…</p>
      ) : (
        <>
          <h2>{detail.name}</h2>
          <p className="muted">Profesor: {detail.ownerEmail}</p>
          <h3>Tareas</h3>
          {detail.tasks.length === 0 ? (
            <p className="muted">Aún no hay tareas en esta clase.</p>
          ) : (
            <ul className="tasklist">
              {detail.tasks.map((t) => (
                <li
                  key={t.taskId}
                  className="taskitem clickable"
                  onClick={() => setOpenTask(t)}
                >
                  <div>
                    <div className="taskname">{t.title}</div>
                    <div className="small">
                      <DueLabel dueDate={t.dueDate} />
                    </div>
                  </div>
                  <span className="muted small">
                    {t.submissionJobId ? "✓ entregado · ver" : "Entregar →"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  );
}

// P3: vista de resultado enfocada para el alumno (su retroalimentación).
function StudentResult({ jobId, onResubmit }) {
  const [data, setData] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const d = await getJob(jobId);
        if (!active) return;
        setData(d);
        const r = (d.results && d.results[0]) || null;
        const settled = r && (r.status === "DONE" || r.status === "FAILED");
        if (!settled) timer.current = setTimeout(poll, 2500);
      } catch {
        if (active) timer.current = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobId]);

  const r = data && data.results && data.results[0];

  if (!r || ["PENDING", "PROCESSING", "RETRYING"].includes(r.status)) {
    return (
      <div className="resultwrap">
        <div className="evaluating">
          <div className="spinner" />
          <p className="muted">Evaluando tu entrega contra la rúbrica…</p>
        </div>
      </div>
    );
  }

  if (r.status === "FAILED") {
    return (
      <div className="resultwrap">
        <div className="error">No se pudo evaluar tu entrega. {r.last_error || ""}</div>
        <button className="btn primary" onClick={onResubmit}>
          Volver a intentar
        </button>
      </div>
    );
  }

  const crit = r.criterios || [];
  const met = crit.filter((c) => c.cumple).length;
  const kind = r.cumplimiento >= 70 ? "good" : r.cumplimiento >= 40 ? "mid" : "bad";

  return (
    <div className="resultwrap">
      <div className="scorehead">
        <div className={"scorering " + kind}>
          <span className="scorenum">{r.cumplimiento}%</span>
        </div>
        <div>
          <div className="scorelabel">Cumplimiento</div>
          <div className="muted">
            Cumples {met} de {crit.length} criterios
          </div>
        </div>
      </div>

      {crit.length > 0 ? (
        <div className="criterios">
          {crit.map((c, i) => (
            <div key={i} className={"crit " + (c.cumple ? "ok" : "bad")}>
              <div className="crithead">
                <span className="critmark">{c.cumple ? "✓" : "✗"}</span>
                <span className="crittitle">{c.criterio}</span>
              </div>
              {c.evidencia && <div className="critev">{c.evidencia}</div>}
              {!c.cumple && c.sugerencia && <div className="critsug">→ {c.sugerencia}</div>}
            </div>
          ))}
        </div>
      ) : (
        <>
          <Section title="✓ Criterios cumplidos" items={r.criterios_ok} kind="ok" />
          <Section title="✗ Faltantes" items={r.faltantes} kind="bad" />
          <Section title="→ Sugerencias" items={r.sugerencias} kind="sug" />
        </>
      )}

      <button className="btn ghost" onClick={onResubmit} style={{ marginTop: 18 }}>
        Volver a entregar
      </button>
    </div>
  );
}

// F5: el alumno entrega su PDF/Word a una tarea -> pipeline -> su retroalimentación.
function TaskSubmit({ classId, task, onBack }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [error, setError] = useState(null);
  const [jobId, setJobId] = useState(task.submissionJobId || null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!files.length) {
      setError("Sube al menos un archivo (PDF, Word o TXT).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setPhase("Extrayendo texto…");
      const { rows, errors } = await filesToRows(files);
      if (!rows.length) {
        setError("No se pudo extraer texto." + (errors.length ? " " + errors.join(" · ") : ""));
        setBusy(false);
        setPhase("");
        return;
      }
      // Toda tu entrega = un solo entregable (se concatenan los archivos subidos).
      const combined = rows.map((r) => r.texto_entrega).join("\n\n").trim();
      const me = currentUser();
      const csv = rowsToCsv([{ id_estudiante: me.name || me.email, texto_entrega: combined }]);
      const blob = new Blob([csv], { type: "text/csv" });

      setPhase("Enviando para evaluación…");
      const { jobId: jid, uploadUrl, headers } = await createTaskUpload(classId, task.taskId);
      await uploadCsv(uploadUrl, headers, blob);
      setJobId(jid);
    } catch (err) {
      setError(err.message);
      setBusy(false);
      setPhase("");
    }
  }

  if (jobId) {
    return (
      <main className="card">
        <button className="btn ghost" onClick={onBack}>
          ← Volver a la clase
        </button>
        <h2>{task.title}</h2>
        <StudentResult jobId={jobId} onResubmit={() => setJobId(null)} />
      </main>
    );
  }

  return (
    <main className="card">
      <button className="btn ghost" onClick={onBack}>
        ← Volver a la clase
      </button>
      <h2>{task.title}</h2>
      <p className="small">
        <DueLabel dueDate={task.dueDate} />
      </p>

      <div className="rubricbox">
        <div className="ilabel">Rúbrica de esta tarea</div>
        <pre className="rubricpre">{task.rubrica || "—"}</pre>
      </div>

      <form onSubmit={handleSubmit}>
        <label>Tu entrega (PDF, Word .docx o TXT)</label>
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          onChange={(e) => setFiles(Array.from(e.target.files || []))}
        />
        {files.length > 0 && (
          <div className="filelist">
            {files.map((f, i) => (
              <div key={i} className="filechip">
                📄 {f.name}
              </div>
            ))}
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <button className="btn primary" disabled={busy}>
          {busy ? phase || "Procesando…" : "Enviar y evaluar"}
        </button>
      </form>
    </main>
  );
}

// Área del profesor (F2/F3): gestión de clases + detalle (roster/invitaciones).
function TeacherClasses() {
  const [classes, setClasses] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [openClass, setOpenClass] = useState(null);

  async function load() {
    try {
      const d = await listClasses();
      setClasses(d.classes || []);
    } catch (e) {
      setError(e.message);
      setClasses([]);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createClass(name.trim());
      setName("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(classId) {
    if (!window.confirm("¿Eliminar esta clase? Se borrarán sus tareas y miembros.")) return;
    setError(null);
    try {
      await deleteClass(classId);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (openClass) {
    return <TeacherClassDetail classId={openClass} onBack={() => setOpenClass(null)} />;
  }

  return (
    <main className="card">
      <h2>Mis clases</h2>
      <p className="muted">
        Crea y gestiona tus clases. Entra en una para invitar estudiantes y crear tareas con su
        rúbrica.
      </p>

      <form onSubmit={onCreate} className="inlineform">
        <input
          type="text"
          value={name}
          placeholder="Nombre de la clase (ej. Cloud Computing 2026-1)"
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn primary" disabled={busy}>
          {busy ? "…" : "Crear clase"}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {classes === null ? (
        <p className="muted">Cargando…</p>
      ) : classes.length === 0 ? (
        <p className="muted">Aún no tienes clases. Crea la primera arriba.</p>
      ) : (
        <ul className="classlist">
          {classes.map((c) => (
            <li key={c.classId} className="classitem">
              <div className="clickarea" onClick={() => setOpenClass(c.classId)}>
                <div className="classname">{c.name}</div>
                <div className="muted small mono">{c.classId}</div>
              </div>
              <div className="rowbtns">
                <button className="btn small" onClick={() => setOpenClass(c.classId)}>
                  Gestionar
                </button>
                <button className="btn small danger" onClick={() => onDelete(c.classId)}>
                  Eliminar
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function TeacherClassDetail({ classId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [editingTask, setEditingTask] = useState(null);
  const [openSubmissions, setOpenSubmissions] = useState(null);

  async function load() {
    try {
      setDetail(await getClassDetail(classId));
    } catch (e) {
      setError(e.message);
    }
  }

  async function onDeleteTask(taskId) {
    if (!window.confirm("¿Eliminar esta tarea?")) return;
    setError(null);
    try {
      await deleteTask(classId, taskId);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, [classId]);

  async function onInvite(e) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await inviteMember(classId, inviteEmail.trim());
      setInviteEmail("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(email) {
    if (!window.confirm(`¿Quitar a ${email} de la clase?`)) return;
    setError(null);
    try {
      await removeMember(classId, email);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (openSubmissions) {
    return (
      <TaskSubmissions
        classId={classId}
        task={openSubmissions}
        onBack={() => setOpenSubmissions(null)}
      />
    );
  }

  return (
    <main className="card">
      <button className="btn ghost" onClick={onBack}>
        ← Volver
      </button>
      {error && <div className="error">{error}</div>}
      {!detail ? (
        <p className="muted">Cargando…</p>
      ) : (
        <>
          <h2>{detail.name}</h2>
          <p className="muted small mono">{detail.classId}</p>

          <h3>Invitar estudiante</h3>
          <form onSubmit={onInvite} className="inlineform">
            <input
              type="email"
              value={inviteEmail}
              placeholder="alumno@utec.edu.pe"
              onChange={(e) => setInviteEmail(e.target.value)}
            />
            <button className="btn primary" disabled={busy}>
              {busy ? "…" : "Invitar"}
            </button>
          </form>

          <h3>Miembros ({detail.members.length})</h3>
          {detail.members.length === 0 ? (
            <p className="muted">Aún no hay miembros. Invita por correo arriba.</p>
          ) : (
            <ul className="memberlist">
              {detail.members.map((m) => (
                <li key={m.email} className="memberitem">
                  <span className="mono">{m.email}</span>
                  <span className={"statuschip " + m.status}>
                    {m.status === "active" ? "activo" : "invitado"}
                  </span>
                  <button className="btn small danger" onClick={() => onRemove(m.email)}>
                    quitar
                  </button>
                </li>
              ))}
            </ul>
          )}

          <h3>Tareas ({detail.tasks.length})</h3>
          {detail.tasks.length > 0 && (
            <ul className="tasklist">
              {detail.tasks.map((t) => (
                <li key={t.taskId} className="taskitem">
                  <div>
                    <div className="taskname">{t.title}</div>
                    <div className="small">
                      <DueLabel dueDate={t.dueDate} />
                      {t.pesos ? <span className="muted"> · pesos: {t.pesos.join(",")}</span> : ""}
                    </div>
                  </div>
                  <div className="rowbtns">
                    <button className="btn small" onClick={() => setOpenSubmissions(t)}>
                      Entregas
                    </button>
                    <button className="btn small" onClick={() => setEditingTask(t)}>
                      Editar
                    </button>
                    <button className="btn small danger" onClick={() => onDeleteTask(t.taskId)}>
                      Eliminar
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <h4 className="formtitle">{editingTask ? "Editar tarea" : "Nueva tarea"}</h4>
          <TaskForm
            key={editingTask ? editingTask.taskId : "new"}
            classId={classId}
            editing={editingTask}
            onSaved={() => {
              setEditingTask(null);
              load();
            }}
            onCancel={() => setEditingTask(null)}
          />
        </>
      )}
    </main>
  );
}

function TaskForm({ classId, editing, onSaved, onCancel }) {
  const [title, setTitle] = useState(editing ? editing.title || "" : "");
  const [rubrica, setRubrica] = useState(editing ? editing.rubrica || "" : DEFAULT_RUBRICA);
  const [pesos, setPesos] = useState(editing && editing.pesos ? editing.pesos.join(",") : "");
  const [dueDate, setDueDate] = useState(editing ? editing.dueDate || "" : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function onSubmit(e) {
    e.preventDefault();
    if (!title.trim()) {
      setError("El título es obligatorio.");
      return;
    }
    const pesosArr = pesos
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean)
      .map(Number);
    if (pesosArr.some((p) => Number.isNaN(p) || p < 0)) {
      setError("Los pesos deben ser números positivos separados por coma.");
      return;
    }
    setBusy(true);
    setError(null);
    const payload = { title: title.trim(), rubrica: rubrica.trim(), pesos: pesosArr, dueDate };
    try {
      if (editing) await updateTask(classId, editing.taskId, payload);
      else await createTask(classId, payload);
      onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="taskform">
      <label>Título de la tarea</label>
      <input
        type="text"
        value={title}
        placeholder="ej. Propuesta de proyecto final"
        onChange={(e) => setTitle(e.target.value)}
      />

      <label>Rúbrica de evaluación</label>
      <textarea rows={5} value={rubrica} onChange={(e) => setRubrica(e.target.value)} />

      <div className="formrow">
        <div>
          <label>
            Pesos <span className="muted small">(opcional · 30,20,20,15,15)</span>
          </label>
          <input
            type="text"
            value={pesos}
            placeholder="vacío = equitativo"
            onChange={(e) => setPesos(e.target.value)}
          />
        </div>
        <div>
          <label>Fecha límite</label>
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="rowbtns">
        <button className="btn primary" disabled={busy}>
          {busy ? "…" : editing ? "Guardar cambios" : "Crear tarea"}
        </button>
        {editing && (
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancelar
          </button>
        )}
      </div>
    </form>
  );
}

// P2: el profesor ve las entregas y resultados de una tarea.
function TaskSubmissions({ classId, task, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  function load() {
    setError(null);
    getTaskSubmissions(classId, task.taskId)
      .then(setData)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, [classId, task.taskId]);

  return (
    <main className="card">
      <div className="detailhead">
        <button className="btn ghost" onClick={onBack}>
          ← Volver
        </button>
        <button
          className="btn small"
          onClick={() => {
            setData(null);
            load();
          }}
        >
          Actualizar
        </button>
      </div>
      <h2>Entregas · {task.title}</h2>
      {error && <div className="error">{error}</div>}
      {!data ? (
        <p className="muted">Cargando…</p>
      ) : (
        <>
          <p className="muted">
            {data.stats.evaluados} de {data.stats.total} entrega(s) evaluada(s)
          </p>
          {data.stats.evaluados > 0 && <InsightsPanel insights={data.stats} />}
          {data.submissions.length === 0 ? (
            <p className="muted">Aún no hay entregas para esta tarea.</p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th>Estudiante</th>
                  <th>Estado</th>
                  <th>Cumplimiento</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.submissions.map((r) => (
                  <tr key={r.studentEmail}>
                    <td className="mono small">{r.studentEmail}</td>
                    <td>
                      <span className={"badge " + r.status}>
                        {STATUS_LABEL[r.status] || r.status}
                      </span>
                    </td>
                    <td>
                      {r.cumplimiento != null ? (
                        <CumpBar v={r.cumplimiento} />
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {r.status === "DONE" && (
                        <button
                          className="btn link"
                          onClick={() => setSelected({ ...r, id_estudiante: r.studentEmail })}
                        >
                          ver detalle
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      {selected && <Detail r={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}

function AuthScreen({ onAuth }) {
  const [mode, setMode] = useState("login"); // login | signup
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") await signup(email.trim(), password, name.trim());
      else await login(email.trim(), password);
      onAuth();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrandMark /> RúbricaIA
        </div>
        <div className="tag">Revisión automática de entregables contra la rúbrica</div>
      </header>

      <main className="card authcard">
        <h2>{mode === "login" ? "Iniciar sesión" : "Crear cuenta"}</h2>
        <p className="muted">Acceso con tu correo institucional <code>@utec.edu.pe</code>.</p>

        <form onSubmit={handleSubmit}>
          {mode === "signup" && (
            <>
              <label>Nombre</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
            </>
          )}
          <label>Correo</label>
          <input
            type="email"
            value={email}
            placeholder="usuario@utec.edu.pe"
            onChange={(e) => setEmail(e.target.value)}
          />
          <label>Contraseña</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && <div className="error">{error}</div>}

          <button className="btn primary" disabled={busy}>
            {busy ? "…" : mode === "login" ? "Entrar" : "Registrarme"}
          </button>
        </form>

        <p className="muted small switchmode">
          {mode === "login" ? "¿No tienes cuenta? " : "¿Ya tienes cuenta? "}
          <button
            className="btn link"
            onClick={() => {
              setError(null);
              setMode(mode === "login" ? "signup" : "login");
            }}
          >
            {mode === "login" ? "Regístrate" : "Inicia sesión"}
          </button>
        </p>
      </main>

      <footer className="foot">
        Plano de control: auth JWT · plano de datos: pipeline serverless event-driven
      </footer>
    </div>
  );
}

function InsightsPanel({ insights }) {
  if (!insights || !insights.evaluados) return null;
  const d = insights.distribucion;
  const total = d.low + d.mid + d.high || 1;
  const top = (insights.criterios_fallados || []).slice(0, 5);

  return (
    <div className="insights">
      <div className="insightcards">
        <div className="icard">
          <div className="inum">{insights.promedio}%</div>
          <div className="ilabel">Promedio de la clase</div>
        </div>
        <div className="icard">
          <div className="inum">{insights.evaluados}</div>
          <div className="ilabel">Entregables evaluados</div>
        </div>
        <div className="icard wide">
          <div className="ilabel">Distribución de cumplimiento</div>
          <div className="distbar">
            <span className="seg bad" style={{ width: (d.low / total) * 100 + "%" }} />
            <span className="seg mid" style={{ width: (d.mid / total) * 100 + "%" }} />
            <span className="seg good" style={{ width: (d.high / total) * 100 + "%" }} />
          </div>
          <div className="distlegend">
            <span><i className="ldot bad" /> Bajo &lt;40% ({d.low})</span>
            <span><i className="ldot mid" /> 40–70% ({d.mid})</span>
            <span><i className="ldot good" /> Alto ≥70% ({d.high})</span>
          </div>
        </div>
      </div>

      {top.length > 0 && (
        <div className="topfail">
          <div className="ilabel">Criterios más fallados de la clase</div>
          <ul className="faillist">
            {top.map((f, i) => (
              <li key={i}>
                <span className="failname">{f.criterio}</span>
                <span className="failbar">
                  <span style={{ width: (f.count / insights.evaluados) * 100 + "%" }} />
                </span>
                <span className="failcount">{f.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CumpBar({ v }) {
  const kind = v >= 70 ? "good" : v >= 40 ? "mid" : "bad";
  return (
    <div className="cump">
      <div className="cumptrack">
        <div className={"cumpbar " + kind} style={{ width: v + "%" }} />
      </div>
      <span className="cumpval">{v}%</span>
    </div>
  );
}

function Detail({ r, onClose }) {
  const hasCriterios = r.criterios && r.criterios.length > 0;
  return (
    <div className="modalbg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modalhead">
          <h3>
            {r.id_estudiante} · <span className="mono">{r.cumplimiento}%</span>
          </h3>
          <button className="x" onClick={onClose}>
            ×
          </button>
        </div>

        {hasCriterios && (
          <p className="critsummary">
            Cumple <strong>{r.criterios.filter((c) => c.cumple).length}</strong> de{" "}
            {r.criterios.length} criterios · {r.cumplimiento}%
          </p>
        )}

        {hasCriterios ? (
          <div className="criterios">
            {r.criterios.map((c, i) => (
              <div key={i} className={"crit " + (c.cumple ? "ok" : "bad")}>
                <div className="crithead">
                  <span className="critmark">{c.cumple ? "✓" : "✗"}</span>
                  <span className="crittitle">{c.criterio}</span>
                </div>
                {c.evidencia && <div className="critev">{c.evidencia}</div>}
                {!c.cumple && c.sugerencia && (
                  <div className="critsug">→ {c.sugerencia}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <>
            <Section title="✓ Criterios cumplidos" items={r.criterios_ok} kind="ok" />
            <Section title="✗ Faltantes" items={r.faltantes} kind="bad" />
            <Section title="→ Sugerencias" items={r.sugerencias} kind="sug" />
          </>
        )}
      </div>
    </div>
  );
}

function Section({ title, items, kind }) {
  return (
    <div className="section">
      <h4>{title}</h4>
      {items && items.length ? (
        <ul className={"list " + kind}>
          {items.map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">—</p>
      )}
    </div>
  );
}
