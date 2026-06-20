import { useState, useEffect, useRef } from "react";
import { createUpload, uploadCsv, getJob, getReport, retryFailed } from "./api";
import { filesToRows, rowsToCsv } from "./extract";
import { currentUser, login, signup, clearToken } from "./auth";
import { listClasses, createClass, deleteClass } from "./lms";

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
          <span className="dot" /> RúbricaIA
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

// Área del estudiante: por ahora mantiene el flujo de subida directo.
// En F5 se moverá dentro de las tareas de cada clase.
function StudentArea() {
  const [view, setView] = useState("upload");
  const [jobId, setJobId] = useState(null);

  return view === "upload" ? (
    <UploadView
      onStarted={(id) => {
        setJobId(id);
        setView("dashboard");
      }}
    />
  ) : (
    <Dashboard
      jobId={jobId}
      onNew={() => {
        setView("upload");
        setJobId(null);
      }}
    />
  );
}

// Área del profesor (F2): gestión de clases.
function TeacherClasses() {
  const [classes, setClasses] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

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

  return (
    <main className="card">
      <h2>Mis clases</h2>
      <p className="muted">
        Crea y gestiona tus clases. Luego podrás invitar estudiantes y crear tareas con su rúbrica.
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
              <div>
                <div className="classname">{c.name}</div>
                <div className="muted small mono">{c.classId}</div>
              </div>
              <button className="btn small danger" onClick={() => onDelete(c.classId)}>
                Eliminar
              </button>
            </li>
          ))}
        </ul>
      )}
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
          <span className="dot" /> RúbricaIA
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

function UploadView({ onStarted }) {
  const [rubrica, setRubrica] = useState(DEFAULT_RUBRICA);
  const [pesosStr, setPesosStr] = useState("");
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!files.length) {
      setError("Selecciona al menos un archivo (PDF, Word, TXT o CSV).");
      return;
    }
    // F5: pesos opcionales por criterio (separados por coma).
    const pesos = pesosStr
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean)
      .map(Number);
    if (pesos.some((p) => Number.isNaN(p) || p < 0)) {
      setError("Los pesos deben ser números positivos separados por coma.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setPhase("Extrayendo texto de los archivos…");
      const { rows, errors } = await filesToRows(files);
      if (!rows.length) {
        setError(
          "No se pudo extraer texto de los archivos." +
            (errors.length ? " " + errors.join(" · ") : "")
        );
        setBusy(false);
        setPhase("");
        return;
      }
      if (errors.length) setError("Algunos archivos se omitieron: " + errors.join(" · "));

      setPhase(`Subiendo ${rows.length} entregable${rows.length > 1 ? "s" : ""}…`);
      const csv = rowsToCsv(rows);
      const blob = new Blob([csv], { type: "text/csv" });
      const { jobId, uploadUrl, headers } = await createUpload(rubrica, pesos);
      await uploadCsv(uploadUrl, headers, blob);
      onStarted(jobId);
    } catch (err) {
      setError("No se pudo iniciar el procesamiento: " + err.message);
      setBusy(false);
      setPhase("");
    }
  }

  return (
    <main className="card">
      <h2>Subir lote de entregables</h2>
      <p className="muted">
        Sube los trabajos de los estudiantes en <strong>PDF, Word (.docx), TXT</strong> o un{" "}
        <strong>CSV</strong>. Cada archivo es un entregable (un CSV se expande por filas) y se
        evalúa contra la rúbrica de forma asíncrona e independiente.
      </p>

      <form onSubmit={handleSubmit}>
        <label>Rúbrica de evaluación</label>
        <textarea rows={6} value={rubrica} onChange={(e) => setRubrica(e.target.value)} />

        <label>
          Pesos por criterio <span className="muted small">(opcional · ej. 30,20,20,15,15)</span>
        </label>
        <input
          type="text"
          value={pesosStr}
          placeholder="Deja vacío para ponderación equitativa"
          onChange={(e) => setPesosStr(e.target.value)}
        />

        <label>Entregables (PDF, Word, TXT o CSV)</label>
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.csv"
          onChange={(e) => setFiles(Array.from(e.target.files || []))}
        />
        {files.length > 0 && (
          <div className="filelist">
            <div className="muted small">
              {files.length} archivo{files.length > 1 ? "s" : ""} seleccionado
              {files.length > 1 ? "s" : ""}
            </div>
            {files.map((f, i) => (
              <div key={i} className="filechip">
                📄 {f.name}
              </div>
            ))}
          </div>
        )}

        {error && <div className="error">{error}</div>}

        <button className="btn primary" disabled={busy}>
          {busy ? phase || "Procesando…" : "Procesar lote"}
        </button>
      </form>
    </main>
  );
}

function Dashboard({ jobId, onNew }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [retrying, setRetrying] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const timer = useRef(null);
  const reportPolls = useRef(0);

  async function doRetry() {
    setRetrying(true);
    try {
      await retryFailed(jobId);
      reportPolls.current = 0;
      setRetryNonce((n) => n + 1); // reinicia el polling
    } catch {
      /* sin-op: el usuario puede reintentar */
    } finally {
      setRetrying(false);
    }
  }

  useEffect(() => {
    let active = true;
    reportPolls.current = 0;

    async function poll() {
      try {
        const d = await getJob(jobId);
        if (!active) return;
        setData(d);
        // Sigue sondeando mientras el lote no termina; una vez DONE, da unos
        // sondeos extra hasta que el reporte (Fase 3B) quede listo.
        const done = d.jobStatus === "DONE";
        if (!done) {
          timer.current = setTimeout(poll, 2500);
        } else if (!d.reportReady && reportPolls.current < 10) {
          reportPolls.current += 1;
          timer.current = setTimeout(poll, 2500);
        }
      } catch {
        if (active) timer.current = setTimeout(poll, 3000);
      }
    }

    poll();
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobId, retryNonce]);

  if (!data) {
    return (
      <main className="card">
        <p className="muted">Cargando resultados…</p>
      </main>
    );
  }

  const pct = data.total ? Math.round((data.done / data.total) * 100) : 0;
  const running = data.jobStatus !== "DONE";

  return (
    <main className="card">
      <div className="dashhead">
        <div>
          <h2>
            Resultados del lote{" "}
            {data.completed && (
              <span className="notified" title="El docente fue notificado por email (SNS)">
                ✉️ Docente notificado
              </span>
            )}
          </h2>
          <div className="muted mono">{jobId}</div>
        </div>
        <button className="btn ghost" onClick={onNew}>
          ← Nuevo lote
        </button>
      </div>

      <div className="progress">
        <div className="progressbar">
          <span style={{ width: pct + "%" }} className={running ? "live" : ""} />
        </div>
        <div className="muted">
          {data.done}/{data.total} procesados
          {data.failed > 0 ? ` · ${data.failed} con error` : ""} · estado {data.jobStatus}
        </div>
      </div>

      {data.failed > 0 && (
        <div className="retrybar">
          <span>
            ⚠️ {data.failed} entregable{data.failed > 1 ? "s" : ""} en error. Puedes
            re-encolarlo{data.failed > 1 ? "s" : ""} sin perder datos.
          </span>
          <button className="btn small" disabled={retrying} onClick={doRetry}>
            {retrying ? "Re-encolando…" : "↺ Reprocesar fallidos"}
          </button>
        </div>
      )}

      {data.similarCount > 0 && (
        <div className="similalert">
          🔍 {data.similarCount} par{data.similarCount > 1 ? "es" : ""} de entregables con
          alta similitud (posible copia). Ver detalle en el reporte de clase.
        </div>
      )}

      {!running && <ReportBar jobId={jobId} ready={data.reportReady} />}

      {data.insights && <InsightsPanel insights={data.insights} />}

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
          {data.results.map((r) => (
            <tr key={r.id_estudiante}>
              <td className="mono">{r.id_estudiante}</td>
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
                  <button className="btn link" onClick={() => setSelected(r)}>
                    ver detalle
                  </button>
                )}
                {r.status === "FAILED" && <span className="muted small">{r.last_error}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && <Detail r={selected} onClose={() => setSelected(null)} />}
    </main>
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

function ReportBar({ jobId, ready }) {
  const [busy, setBusy] = useState(null);

  async function open(format) {
    setBusy(format);
    try {
      const r = await getReport(jobId, format);
      if (r.ready && r.url) window.open(r.url, "_blank", "noopener");
    } catch {
      /* el reporte aún puede estar generándose */
    } finally {
      setBusy(null);
    }
  }

  if (!ready) {
    return (
      <div className="reportbar">
        <span className="muted">⏳ Generando el reporte de clase…</span>
      </div>
    );
  }

  return (
    <div className="reportbar">
      <span className="reportlabel">📄 Reporte de clase</span>
      <div className="reportbtns">
        <button className="btn small" disabled={busy} onClick={() => open("html")}>
          {busy === "html" ? "…" : "Ver HTML"}
        </button>
        <button className="btn small" disabled={busy} onClick={() => open("csv")}>
          {busy === "csv" ? "…" : "CSV"}
        </button>
        <button className="btn small" disabled={busy} onClick={() => open("json")}>
          {busy === "json" ? "…" : "JSON"}
        </button>
      </div>
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
