// Extracción de texto en el navegador.
// Convierte los archivos que sube el docente (PDF, Word .docx, .txt/.md, .csv)
// en filas { id_estudiante, texto_entrega } y arma un único CSV para el backend.
// Cada archivo individual = un entregable (id = nombre del archivo). Un .csv se
// expande por sus filas. Así el backend NO cambia: sigue recibiendo submissions.csv.

const MAX_CHARS = 40000; // cota por entregable (evita pasar el límite de 256KB de SQS)

function baseName(name) {
  const justFile = name.split(/[\\/]/).pop() || name;
  return justFile.replace(/\.[^.]+$/, "").trim() || justFile;
}

function clean(text) {
  return (text || "").replace(/\s+\n/g, "\n").trim().slice(0, MAX_CHARS);
}

// --- PDF (pdf.js global window.pdfjsLib) -----------------------------------
async function pdfText(file) {
  if (!window.pdfjsLib) throw new Error("pdf.js no cargó");
  const buf = await file.arrayBuffer();
  const pdf = await window.pdfjsLib.getDocument({ data: buf }).promise;
  let out = "";
  for (let p = 1; p <= pdf.numPages; p++) {
    const page = await pdf.getPage(p);
    const content = await page.getTextContent();
    out += content.items.map((it) => it.str).join(" ") + "\n";
  }
  return out;
}

// --- Word .docx (mammoth global window.mammoth) ----------------------------
async function docxText(file) {
  if (!window.mammoth) throw new Error("mammoth no cargó");
  const arrayBuffer = await file.arrayBuffer();
  const res = await window.mammoth.extractRawText({ arrayBuffer });
  return res.value || "";
}

// --- CSV: parser mínimo RFC-4180 (soporta comillas, comas y saltos) --------
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += c;
  }
  if (field.length || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((v) => (v || "").trim() !== ""));
}

function csvToRows(text) {
  const matrix = parseCsv(text);
  if (!matrix.length) return [];
  const header = matrix[0].map((h) => h.trim().toLowerCase());
  const idIdx = header.indexOf("id_estudiante");
  const txtIdx = header.indexOf("texto_entrega");
  // Con cabecera estándar respetamos sus columnas; si no, asumimos col0=id, col1=texto.
  const out = [];
  for (let i = idIdx >= 0 || txtIdx >= 0 ? 1 : 0; i < matrix.length; i++) {
    const r = matrix[i];
    const id = (idIdx >= 0 ? r[idIdx] : r[0]) || `fila-${i}`;
    const txt = txtIdx >= 0 ? r[txtIdx] : r[1] || "";
    if ((txt || "").trim()) out.push({ id_estudiante: id.trim(), texto_entrega: txt });
  }
  return out;
}

// --- API del módulo --------------------------------------------------------
export async function filesToRows(files) {
  const rows = [];
  const errors = [];
  for (const file of files) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    try {
      if (ext === "csv") {
        rows.push(...csvToRows(await file.text()));
      } else if (ext === "pdf") {
        rows.push({ id_estudiante: baseName(file.name), texto_entrega: await pdfText(file) });
      } else if (ext === "docx") {
        rows.push({ id_estudiante: baseName(file.name), texto_entrega: await docxText(file) });
      } else if (ext === "doc") {
        errors.push(`${file.name}: .doc antiguo no soportado, conviértelo a .docx o PDF`);
      } else {
        rows.push({ id_estudiante: baseName(file.name), texto_entrega: await file.text() });
      }
    } catch (e) {
      errors.push(`${file.name}: ${e.message || "no se pudo leer"}`);
    }
  }

  // Normaliza y descarta vacíos.
  const cleaned = rows
    .map((r) => ({ id_estudiante: (r.id_estudiante || "").trim(), texto_entrega: clean(r.texto_entrega) }))
    .filter((r) => r.texto_entrega.length > 0);

  // Garantiza ids únicos (dos archivos con el mismo nombre).
  const seen = {};
  for (const r of cleaned) {
    if (seen[r.id_estudiante] != null) {
      seen[r.id_estudiante] += 1;
      r.id_estudiante = `${r.id_estudiante}-${seen[r.id_estudiante]}`;
    } else seen[r.id_estudiante] = 0;
  }

  return { rows: cleaned, errors };
}

export function rowsToCsv(rows) {
  const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const lines = ["id_estudiante,texto_entrega"];
  for (const r of rows) lines.push(`${esc(r.id_estudiante)},${esc(r.texto_entrega)}`);
  return lines.join("\n");
}
