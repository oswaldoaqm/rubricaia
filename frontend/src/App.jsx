import { useState, useEffect, useRef } from "react";
import { createUpload, uploadCsv, getJob } from "./api";

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
  const [view, setView] = useState("upload");
  const [jobId, setJobId] = useState(null);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="dot" /> RúbricaIA
        </div>
        <div className="tag">Revisión automática de entregables contra la rúbrica</div>
      </header>

      {view === "upload" && (
        <UploadView
          onStarted={(id) => {
            setJobId(id);
            setView("dashboard");
          }}
        />
      )}

      {view === "dashboard" && (
        <Dashboard
          jobId={jobId}
          onNew={() => {
            setView("upload");
            setJobId(null);
          }}
        />
      )}

      <footer className="foot">
        Arquitectura serverless basada en eventos · S3 → SQS → Lambda → Groq · AWS Learner Lab
      </footer>
    </div>
  );
}

function UploadView({ onStarted }) {
  const [rubrica, setRubrica] = useState(DEFAULT_RUBRICA);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file) {
      setError("Selecciona un archivo CSV.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { jobId, uploadUrl, headers } = await createUpload(rubrica);
      await uploadCsv(uploadUrl, headers, file);
      onStarted(jobId);
    } catch (err) {
      setError("No se pudo iniciar el procesamiento: " + err.message);
      setBusy(false);
    }
  }

  return (
    <main className="card">
      <h2>Subir lote de entregables</h2>
      <p className="muted">
        Sube un CSV con columnas <code>id_estudiante, texto_entrega</code>. Cada fila se evalúa
        contra la rúbrica de forma asíncrona e independiente.
      </p>

      <form onSubmit={handleSubmit}>
        <label>Rúbrica de evaluación</label>
        <textarea rows={6} value={rubrica} onChange={(e) => setRubrica(e.target.value)} />

        <label>Archivo CSV</label>
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files[0] || null)} />
        {file && <div className="filechip">📄 {file.name}</div>}

        {error && <div className="error">{error}</div>}

        <button className="btn primary" disabled={busy}>
          {busy ? "Subiendo…" : "Procesar lote"}
        </button>
      </form>
    </main>
  );
}

function Dashboard({ jobId, onNew }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const d = await getJob(jobId);
        if (!active) return;
        setData(d);
        if (d.jobStatus !== "DONE") {
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
  }, [jobId]);

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
          <h2>Resultados del lote</h2>
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
        <Section title="✓ Criterios cumplidos" items={r.criterios_ok} kind="ok" />
        <Section title="✗ Faltantes" items={r.faltantes} kind="bad" />
        <Section title="→ Sugerencias" items={r.sugerencias} kind="sug" />
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
