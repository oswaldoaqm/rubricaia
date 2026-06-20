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

Despliegue (Serverless Framework):
  - Runtime : python3.12 / Handler: report_lambda.handler / Role: LabRole
  - Evento  : EventBridge rule (ver serverless.yml: JobCompletedRule)

Variables de entorno:
  TABLE_NAME = rubricaia-<stage>
  BUCKET     = rubricaia-inputs-<acct>-<stage>
"""

import os
import io
import csv
import json
import html
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET = os.environ["BUCKET"]

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
  <div class="topfail"><div class="lbl">Criterios más fallados de la clase</div><ul>{top}</ul></div>
  <table><thead><tr><th>Estudiante</th><th>Estado</th><th>Cumplimiento</th><th>Faltantes</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
  <div class="foot">RúbricaIA · reporte generado automáticamente por la Report Lambda vía EventBridge</div>
</div></body></html>"""


def _pct(part, whole):
    return round((part / whole) * 100) if whole else 0


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

    # Marca el reporte como listo para que la API/Frontend ofrezcan la descarga.
    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "META"},
        UpdateExpression="SET report_ready = :t, report_at = :ts, updatedAt = :ts",
        ExpressionAttributeValues={":t": True, ":ts": now_iso()},
    )

    print(f"Reporte generado para {job_id}: {base}/report.{{json,csv,html}}")
    return {"ok": True, "jobId": job_id}
