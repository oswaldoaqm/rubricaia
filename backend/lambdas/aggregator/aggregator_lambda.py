"""
RúbricaIA - Aggregator Lambda
=============================
Disparador : DynamoDB Streams de la tabla rubricaia (NEW_AND_OLD_IMAGES).
Funcion    : cada vez que un entregable (ITEM#) pasa a DONE, recalcula en
             tiempo real las estadisticas de la clase (item STATS) y el ranking
             de criterios mas fallados (items FAIL#<criterio>).

Por que asi (arquitectura event-driven):
  El dato que cambia DISPARA el agregado. No hay polling ni recalculo masivo:
  cada transicion a DONE emite un evento de stream que actualiza los contadores
  de forma incremental y atomica (ADD), idempotente respecto a duplicados.

Items que mantiene (misma particion del job):
  PK=JOB#<id> SK=STATS              -> done_count, failed_count, cumplimiento_sum,
                                       dist_low/mid/high, completed (flag)
  PK=JOB#<id> SK=FAIL#<criterio>    -> fail_count, criterio

Fase 3B - cierre del ciclo por eventos:
  Cuando (done + failed) alcanza el total del job, el Aggregator publica UNA sola
  vez un evento "JobCompleted" en el bus de EventBridge (BUS_NAME). El bus hace
  fan-out a SNS (email al docente) y a la Report Lambda (reporte de clase).
  La emision unica se garantiza con una escritura condicional sobre STATS
  (attribute_not_exists(completed)): aunque el stream reentregue, el evento sale
  una sola vez.

Despliegue (Serverless Framework):
  - Runtime : python3.12 / Handler: aggregator_lambda.handler / Role: LabRole
  - Evento  : stream dynamodb (ver serverless.yml)

Variables de entorno:
  TABLE_NAME = rubricaia-<stage>
  BUS_NAME   = rubricaia-events-<stage>   (bus de EventBridge; Fase 3B)
"""

import os
import json
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
BUS_NAME = os.environ.get("BUS_NAME", "")
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
events = boto3.client("events")
_deser = TypeDeserializer()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _img(image):
    """Convierte una imagen de stream (formato DynamoDB) a dict normal."""
    return {k: _deser.deserialize(v) for k, v in (image or {}).items()}


def handler(event, context):
    for record in event.get("Records", []):
        if record.get("eventName") not in ("INSERT", "MODIFY"):
            continue

        dynamo = record.get("dynamodb", {})
        new = _img(dynamo.get("NewImage"))
        if not new:
            continue

        sk = new.get("SK", "")
        if not sk.startswith("ITEM#"):
            continue  # solo nos interesan los entregables

        status = new.get("status")
        old = _img(dynamo.get("OldImage"))
        old_status = old.get("status")
        pk = new["PK"]

        # Cada transicion terminal cuenta UNA sola vez (old != status terminal).
        if status == "DONE" and old_status != "DONE":
            _update_stats(
                pk=pk,
                cumplimiento=int(new.get("cumplimiento", 0) or 0),
                criterios=new.get("criterios", []) or [],
            )
            _maybe_emit_completion(pk)
        elif status == "FAILED" and old_status != "FAILED":
            _incr_failed(pk)
            _maybe_emit_completion(pk)

    return {"ok": True}


def _update_stats(pk, cumplimiento, criterios):
    # Distribucion por tramos de cumplimiento.
    bucket = "high" if cumplimiento >= 70 else "mid" if cumplimiento >= 40 else "low"

    # Contadores globales del job (ADD crea los atributos si no existen).
    table.update_item(
        Key={"PK": pk, "SK": "STATS"},
        UpdateExpression=f"ADD done_count :one, cumplimiento_sum :c, dist_{bucket} :one",
        ExpressionAttributeValues={":one": Decimal(1), ":c": Decimal(cumplimiento)},
    )

    # Ranking de criterios mas fallados (un item por criterio fallado).
    for c in criterios:
        if not isinstance(c, dict) or c.get("cumple"):
            continue
        name = str(c.get("criterio", "")).strip()[:120]
        if not name:
            continue
        table.update_item(
            Key={"PK": pk, "SK": f"FAIL#{name}"},
            UpdateExpression="SET criterio = :n ADD fail_count :one",
            ExpressionAttributeValues={":n": name, ":one": Decimal(1)},
        )


def _incr_failed(pk):
    """Cuenta un entregable que termino en FAILED (para detectar el cierre del job)."""
    table.update_item(
        Key={"PK": pk, "SK": "STATS"},
        UpdateExpression="ADD failed_count :one",
        ExpressionAttributeValues={":one": Decimal(1)},
    )


def _maybe_emit_completion(pk):
    """
    Si el lote completo (done + failed == total), publica UNA sola vez el evento
    JobCompleted en EventBridge. La unicidad se garantiza con una escritura
    condicional sobre STATS.completed (attribute_not_exists).
    """
    meta = table.get_item(Key={"PK": pk, "SK": "META"}).get("Item") or {}
    total = int(meta.get("total", 0) or 0)
    if total <= 0:
        return  # META aun sin total (el Splitter todavia no termino): se reintentara

    stats = table.get_item(Key={"PK": pk, "SK": "STATS"}).get("Item") or {}
    done = int(stats.get("done_count", 0) or 0)
    failed = int(stats.get("failed_count", 0) or 0)
    if done + failed < total:
        return  # todavia faltan entregables por resolver

    # Marca 'completed' de forma atomica: solo el PRIMERO que llegue aqui emite.
    try:
        table.update_item(
            Key={"PK": pk, "SK": "STATS"},
            UpdateExpression="SET completed = :t, completed_at = :ts",
            ConditionExpression="attribute_not_exists(completed)",
            ExpressionAttributeValues={":t": True, ":ts": now_iso()},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return  # ya se emitio antes: no duplicar
        raise

    job_id = pk.split("JOB#", 1)[1]
    promedio = round(int(stats.get("cumplimiento_sum", 0) or 0) / done) if done else 0
    _put_completed_event(job_id, total, done, failed, promedio)


def _put_completed_event(job_id, total, done, failed, promedio):
    """Publica el evento de dominio 'JobCompleted' en el bus de EventBridge."""
    if not BUS_NAME:
        print("BUS_NAME no configurado: se omite la emision de JobCompleted")
        return
    events.put_events(
        Entries=[
            {
                "Source": "rubricaia.aggregator",
                "DetailType": "JobCompleted",
                "EventBusName": BUS_NAME,
                "Detail": json.dumps(
                    {
                        "jobId": job_id,
                        "total": total,
                        "done": done,
                        "failed": failed,
                        "promedio": promedio,
                    }
                ),
            }
        ]
    )
    print(f"JobCompleted emitido: {job_id} (done={done} failed={failed} total={total})")
