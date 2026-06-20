"""
RúbricaIA - Report Lambda (Fase 3B)
===================================
Disparador : EventBridge, regla JobCompleted del bus `rubricaia-events`.
             (El Aggregator publica el evento cuando el lote termina.)
Funcion    : arma el REPORTE DE CLASE de un job y lo deja descargable en S3 en
             tres formatos (CSV, JSON, HTML), luego marca `report_ready` en META.

Por que asi (arquitectura event-driven):
  El reporte NO se calcula en el camino critico ni por polling: lo dispara el
  evento de dominio "el lote termino". Es un consumidor independiente del bus
  (el otro es SNS -> email al docente). Agregar/quitar consumidores no toca al
  productor.

Salida en S3 (mismo bucket de entrada, prefijo reports/):
  reports/<jobId>/report.json   (maquina / reproducibilidad)
  reports/<jobId>/report.csv    (el docente lo abre en Excel)
  reports/<jobId>/report.html   (reporte visual autocontenido)
"""

import os
import io
import re
import csv
import json
import math
import html
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET = os.environ["BUCKET"]

# F2: resumen ejecutivo por LLM (reusa la integracion Groq; env compartida).
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# F4: umbral de similitud para marcar posible copia (coseno TF-IDF, 0..1).
SIM_THRESHOLD = float(os.environ.get("SIM_THRESHOLD", "0.6"))

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _num(o):
    """JSON encoder para Decimal de DynamoDB."""
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def _i(v):
    return int(v) if v is not None else 0


# --- carga de datos del job ------------------------------------------------
def _load_items(job_id):
    items = []
    resp = table.query(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}"))
    items += resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}"),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items += resp.get("Items", [])
    return items


# --- calculo del reporte (autocontenido: se recalcula desde los items) -----
def _build_report(job_id, items):
    meta = next((i for i in items if i["SK"] == "META"), {}) or {}
    entregables = sorted(
        [i for i in items if i["SK"].startswith("ITEM#")],
        key=lambda x: x.get("id_estudiante") or "",
    )

    done_items = [e for e in entregables if e.get("status") == "DONE"]
    failed_items = [e for e in entregables if e.get("status") == "FAILED"]
    cumpls = [_i(e.get("cumplimiento")) for e in done_items]

    promedio = round(sum(cumpls) / len(cumpls)) if cumpls else 0
    dist = {"low": 0, "mid": 0, "high": 0}
    for c in cumpls:
        dist["high" if c >= 70 else "mid" if c >= 40 else "low"] += 1

    # Ranking de criterios mas fallados (recalculado desde los entregables DONE).
    fail_counter = {}
    for e in done_items:
        for c in e.get("criterios", []) or []:
            if isinstance(c, dict) and not c.get("cumple"):
                name = str(c.get("criterio", "")).strip()
                if name:
                    fail_counter[name] = fail_counter.get(name, 0) + 1
    criterios_fallados = sorted(
        [{"criterio": k, "count": v} for k, v in fail_counter.items()],
        key=lambda x: -x["count"],
    )

    resultados = [
        {
            "id_estudiante": e.get("id_estudiante"),
            "status": e.get("status"),
            "cumplimiento": _i(e.get("cumplimiento")) if e.get("cumplimiento") is not None else None,
            "criterios": e.get("criterios", []) or [],
            "criterios_ok": e.get("criterios_ok", []) or [],
            "faltantes": e.get("faltantes", []) or [],
            "sugerencias": e.get("sugerencias", []) or [],
            "last_error": e.get("last_error"),
        }
        for e in entregables
    ]

    return {
        "jobId": job_id,
        "generadoEn": now_iso(),
        "rubrica": meta.get("rubrica", ""),
        "resumen": {
            "total": _i(meta.get("total")) or len(entregables),
            "evaluados": len(done_items),
            "con_error": len(failed_items),
            "promedio": promedio,
            "distribucion": dist,
        },
        "criterios_mas_fallados": criterios_fallados,
        "resultados": resultados,
    }


# --- serializadores --------------------------------------------------------
def _to_csv(rep):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["id_estudiante", "status", "cumplimiento", "criterios_ok", "faltantes", "sugerencias"]
    )
    for r in rep["resultados"]:
        w.writerow(
            [
                r["id_estudiante"],
                r["status"],
                "" if r["cumplimiento"] is None else r["cumplimiento"],
                " | ".join(r["criterios_ok"]),
                " | ".join(r["faltantes"]),
                " | ".join(r["sugerencias"]),
            ]
        )
    return buf.getvalue()


def _to_html(rep):
    s = rep["resumen"]
    d = s["distribucion"]
    e = html.escape

    def bar(pct, kind):
        return (
            f'<div class="track"><div class="fill {kind}" style="width:{pct}%"></div></div>'
        )

    rows = []
    for r in rep["resultados"]:
        cump = "—" if r["cumplimiento"] is None else f'{r["cumplimiento"]}%'
        kind = "bad"
        if r["cumplimiento"] is not None:
            kind = "good" if r["cumplimiento"] >= 70 else "mid" if r["cumplimiento"] >= 40 else "bad"
        falt = "".join(f"<li>{e(x)}</li>" for x in r["faltantes"]) or "<li class='muted'>—</li>"
        rows.append(
            f"<tr><td class='mono'>{e(str(r['id_estudiante']))}</td>"
            f"<td><span class='badge {e(str(r['status']))}'>{e(str(r['status']))}</span></td>"
            f"<td class='cump'>{cump}{bar(r['cumplimiento'] or 0, kind)}</td>"
            f"<td><ul class='falt'>{falt}</ul></td></tr>"
        )

    top = "".join(
        f"<li><span>{e(c['criterio'])}</span><b>{c['count']}</b></li>"
        for c in rep["criterios_mas_fallados"][:8]
    ) or "<li class='muted'>Sin criterios fallados</li>"

    # F2: bloque de resumen ejecutivo (si el LLM lo genero).
    resumen = rep.get("resumen_ejecutivo")
    if resumen and (resumen.get("resumen") or resumen.get("recomendaciones")):
        recs = "".join(f"<li>{e(r)}</li>" for r in resumen.get("recomendaciones", []))
        resumen_html = (
            '<div class="summary"><div class="lbl">🧠 Resumen ejecutivo (IA)</div>'
            f"<p>{e(resumen.get('resumen', ''))}</p><ul class='recs'>{recs}</ul></div>"
        )
    else:
        resumen_html = ""

    # F4: bloque de posibles coincidencias (anti-copia).
    sim = rep.get("similitud", [])
    if sim:
        sim_items = "".join(
            f"<li><span class='pair'>{e(str(p['a']))} ↔ {e(str(p['b']))}</span>"
            f"<b>{round(p['score'] * 100)}%</b></li>"
            for p in sim[:10]
        )
        simil_html = (
            f"<div class='simil'><div class='lbl'>⚠️ Posibles coincidencias ({len(sim)})</div>"
            f"<ul>{sim_items}</ul></div>"
        )
    else:
        simil_html = ""

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reporte de clase · {e(rep['jobId'])}</title>
<style>
  :root{{--bg:#0f1419;--card:#1a2230;--mut:#8a97a8;--good:#22c55e;--mid:#eab308;--bad:#ef4444;--ac:#6366f1}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:#e6edf3;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;padding:32px}}
  .wrap{{max-width:980px;margin:0 auto}}
  h1{{margin:0 0 4px;font-size:24px}} .sub{{color:var(--mut);margin-bottom:24px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:24px}}
  .card{{background:var(--card);border:1px solid #2a3445;border-radius:12px;padding:16px}}
  .num{{font-size:30px;font-weight:700}} .lbl{{color:var(--mut);font-size:13px}}
  .distbar{{display:flex;height:12px;border-radius:6px;overflow:hidden;margin-top:8px}}
  .distbar span{{display:block}} .seg.bad{{background:var(--bad)}} .seg.mid{{background:var(--mid)}} .seg.good{{background:var(--good)}}
  table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}}
  th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #2a3445;vertical-align:top}}
  th{{color:var(--mut);font-size:13px;text-transform:uppercase;letter-spacing:.04em}}
  .mono{{font-family:ui-monospace,Menlo,monospace}}
  .badge{{padding:2px 8px;border-radius:999px;font-size:12px;background:#2a3445}}
  .badge.DONE{{background:rgba(34,197,94,.18);color:#86efac}} .badge.FAILED{{background:rgba(239,68,68,.18);color:#fca5a5}}
  .track{{height:6px;background:#2a3445;border-radius:3px;margin-top:4px;width:120px}}
  .fill{{height:100%;border-radius:3px}} .fill.good{{background:var(--good)}} .fill.mid{{background:var(--mid)}} .fill.bad{{background:var(--bad)}}
  ul.falt{{margin:0;padding-left:16px}} ul.falt li{{font-size:13px}}
  .topfail{{background:var(--card);border:1px solid #2a3445;border-radius:12px;padding:16px;margin-bottom:24px}}
  .topfail ul{{list-style:none;margin:8px 0 0;padding:0}}
  .topfail li{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #2a3445}}
  .topfail b{{color:var(--bad)}} .muted{{color:var(--mut)}}
  .summary{{background:linear-gradient(135deg,rgba(99,102,241,.16),rgba(99,102,241,.04));border:1px solid rgba(99,102,241,.4);border-radius:12px;padding:16px;margin-bottom:24px}}
  .summary p{{margin:8px 0}} .recs{{margin:8px 0 0;padding-left:18px}} .recs li{{margin:4px 0}}
  .simil{{background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.4);border-radius:12px;padding:16px;margin-bottom:24px}}
  .simil ul{{list-style:none;margin:8px 0 0;padding:0}}
  .simil li{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #2a3445}}
  .simil .pair{{font-family:ui-monospace,Menlo,monospace}} .simil b{{color:var(--mid)}}
  .foot{{color:var(--mut);font-size:12px;margin-top:20px;text-align:center}}
</style></head><body><div class="wrap">
  <h1>Reporte de clase</h1>
  <div class="sub">Lote <span class="mono">{e(rep['jobId'])}</span> · generado {e(rep['generadoEn'][:19])} UTC</div>
  <div class="cards">
    <div class="card"><div class="num">{s['promedio']}%</div><div class="lbl">Promedio de la clase</div></div>
    <div class="card"><div class="num">{s['evaluados']}</div><div class="lbl">Entregables evaluados</div></div>
    <div class="card"><div class="num">{s['con_error']}</div><div class="lbl">Con error</div></div>
    <div class="card"><div class="lbl">Distribución de cumplimiento</div>
      <div class="distbar"><span class="seg bad" style="width:{_pct(d['low'],s['evaluados'])}%"></span><span class="seg mid" style="width:{_pct(d['mid'],s['evaluados'])}%"></span><span class="seg good" style="width:{_pct(d['high'],s['evaluados'])}%"></span></div>
      <div class="lbl" style="margin-top:6px">Bajo {d['low']} · Medio {d['mid']} · Alto {d['high']}</div>
    </div>
  </div>
  {resumen_html}
  <div class="topfail"><div class="lbl">Criterios más fallados de la clase</div><ul>{top}</ul></div>
  {simil_html}
  <table><thead><tr><th>Estudiante</th><th>Estado</th><th>Cumplimiento</th><th>Faltantes</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
  <div class="foot">RúbricaIA · reporte generado automáticamente por la Report Lambda vía EventBridge</div>
</div></body></html>"""


def _pct(part, whole):
    return round((part / whole) * 100) if whole else 0


# --- F2: resumen ejecutivo de la clase por LLM -----------------------------
def _llm_summary(rep):
    """Una llamada extra a Groq para narrar el desempeno de la clase y recomendar
    acciones. Es best-effort: si Groq falla, el reporte se genera igual sin esto."""
    if not GROQ_API_KEY:
        return None
    s = rep["resumen"]
    top = ", ".join(
        f'{c["criterio"]} ({c["count"]})' for c in rep["criterios_mas_fallados"][:6]
    ) or "ninguno"
    system_prompt = (
        "Eres un asesor pedagogico. Recibes estadisticas agregadas de un lote de "
        "entregables evaluados contra una rubrica. Devuelve UNICAMENTE un objeto JSON "
        "valido con estas claves:\n"
        '  "resumen": 2-3 frases sobre el desempeno general de la clase,\n'
        '  "recomendaciones": lista de 3 acciones concretas y accionables para el docente.\n'
        "Se especifico y util. No agregues texto fuera del JSON."
    )
    user_prompt = (
        f"Total: {s['total']} | Evaluados: {s['evaluados']} | Promedio: {s['promedio']}% | "
        f"Distribucion (bajo/medio/alto): {s['distribucion']['low']}/"
        f"{s['distribucion']['mid']}/{s['distribucion']['high']}.\n"
        f"Criterios mas fallados: {top}.\n"
        f"Rubrica: {rep.get('rubrica', '')[:600]}"
    )
    try:
        body = _groq_chat(system_prompt, user_prompt)
        data = json.loads(body["choices"][0]["message"]["content"])
        recs = data.get("recomendaciones", [])
        if isinstance(recs, str):
            recs = [recs]
        return {
            "resumen": str(data.get("resumen", "")).strip(),
            "recomendaciones": [str(r) for r in recs][:5],
        }
    except Exception as e:  # noqa: BLE001 - el reporte NUNCA falla por el resumen
        print(f"Resumen LLM omitido: {e}")
        return None


def _groq_chat(system_prompt, user_prompt):
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (RubricaIA)",  # Cloudflare: no quitar
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --- F4: deteccion de similitud (TF-IDF + coseno, stdlib puro) -------------
_STOP = set(
    "de la el en y a los las que un una para por con se su del al lo como mas este "
    "esta o e es son ser fue han ha hay le les nos sus pero si no sobre entre".split()
)


def _tokens(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.split(r"[^a-z0-9]+", text) if len(t) >= 3 and t not in _STOP]


def _tfidf(docs):
    n = len(docs)
    df = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
    vecs = []
    for toks in docs:
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        total = len(toks) or 1
        vecs.append({t: (c / total) * idf[t] for t, c in tf.items()})
    return vecs


def _cosine(a, b):
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _find_similar(items):
    subs = [
        (i.get("id_estudiante"), i.get("texto", ""))
        for i in items
        if i["SK"].startswith("ITEM#") and (i.get("texto") or "").strip()
    ]
    vecs = _tfidf([_tokens(t) for _, t in subs])
    pairs = []
    for x in range(len(subs)):
        for y in range(x + 1, len(subs)):
            score = _cosine(vecs[x], vecs[y])
            if score >= SIM_THRESHOLD:
                pairs.append({"a": subs[x][0], "b": subs[y][0], "score": round(score, 3)})
    pairs.sort(key=lambda p: -p["score"])
    return pairs


# --- handler ---------------------------------------------------------------
def handler(event, context):
    detail = event.get("detail", {}) or {}
    job_id = detail.get("jobId")
    if not job_id:
        print("Evento sin jobId; se ignora.")
        return {"ok": False, "error": "no jobId"}

    items = _load_items(job_id)
    if not items:
        print(f"Job {job_id} sin items; se ignora.")
        return {"ok": False, "error": "job vacio"}

    rep = _build_report(job_id, items)
    rep["similitud"] = _find_similar(items)        # F4: pares sospechosos
    rep["resumen_ejecutivo"] = _llm_summary(rep)   # F2: narrativa + recomendaciones
    base = f"reports/{job_id}"

    s3.put_object(
        Bucket=BUCKET,
        Key=f"{base}/report.json",
        Body=json.dumps(rep, default=_num, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{base}/report.csv",
        Body=_to_csv(rep).encode("utf-8-sig"),  # BOM para que Excel respete acentos
        ContentType="text/csv; charset=utf-8",
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{base}/report.html",
        Body=_to_html(rep).encode("utf-8"),
        ContentType="text/html; charset=utf-8",
    )

    # Marca el reporte como listo y publica el nº de pares similares (F4) para que
    # la API/Frontend ofrezcan la descarga y muestren la alerta de posible copia.
    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "META"},
        UpdateExpression=(
            "SET report_ready = :t, report_at = :ts, updatedAt = :ts, similar_count = :sc"
        ),
        ExpressionAttributeValues={
            ":t": True,
            ":ts": now_iso(),
            ":sc": len(rep["similitud"]),
        },
    )

    print(f"Reporte generado para {job_id}: {base}/report.{{json,csv,html}}")
    return {"ok": True, "jobId": job_id}
