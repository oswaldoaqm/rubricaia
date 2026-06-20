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
  PK=JOB#<id> SK=STATS              -> done_count, cumplimiento_sum, dist_low/mid/high
  PK=JOB#<id> SK=FAIL#<criterio>    -> fail_count, criterio

Despliegue (Serverless Framework):
  - Runtime : python3.12 / Handler: aggregator_lambda.handler / Role: LabRole
  - Evento  : stream dynamodb (ver serverless.yml)

Variables de entorno:
  TABLE_NAME = rubricaia-<stage>
"""

import os
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeDeserializer

TABLE_NAME = os.environ["TABLE_NAME"]
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
_deser = TypeDeserializer()


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
        if new.get("status") != "DONE":
            continue

        # Idempotencia: solo contar la PRIMERA vez que pasa a DONE.
        old = _img(dynamo.get("OldImage"))
        if old.get("status") == "DONE":
            continue

        _update_stats(
            pk=new["PK"],
            cumplimiento=int(new.get("cumplimiento", 0) or 0),
            criterios=new.get("criterios", []) or [],
        )

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
