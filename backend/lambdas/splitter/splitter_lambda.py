"""
RúbricaIA - Splitter Lambda
===========================
Disparador : S3 ObjectCreated en el bucket de entrada, prefijo `inputs/`.
Funcion    : lee el CSV subido, crea el registro del JOB en DynamoDB y emite
             UN mensaje SQS por cada fila (entregable). Aqui nace el
             "procesamiento masivo por lotes de 20-30" de la rubrica.

Flujo:
  S3 (inputs/<jobId>/submissions.csv)  -> Splitter
    -> DynamoDB: JOB#<jobId> / META   (status PROCESSING, total = nº filas)
    -> DynamoDB: JOB#<jobId> / ITEM#<id>  (status PENDING)  por cada fila
    -> SQS: un mensaje por fila

Despliegue (AWS Learner Lab):
  - Runtime  : python3.12
  - Handler  : splitter_lambda.handler
  - Role     : LabRole
  - Sin dependencias externas (solo stdlib + boto3).
  - Trigger  : S3 -> Event type "PUT" / ObjectCreated, prefijo `inputs/`, sufijo `.csv`.
  - Timeout  : 60s (suficiente para 20-30 filas).

Variables de entorno:
  TABLE_NAME       = rubricaia
  QUEUE_URL        = https://sqs.<region>.amazonaws.com/<acct>/rubricaia-jobs
  DEFAULT_RUBRICA  = (texto de rubrica por defecto si el objeto S3 no trae metadata 'rubrica')
"""

import os
import csv
import io
import json
import urllib.parse
from datetime import datetime, timezone

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
QUEUE_URL = os.environ["QUEUE_URL"]
DEFAULT_RUBRICA = os.environ.get(
    "DEFAULT_RUBRICA",
    "1) Define un problema real y concreto. "
    "2) Identifica al usuario afectado. "
    "3) Describe el caso de uso. "
    "4) Justifica el impacto esperado con metricas. "
    "5) Redaccion clara y estructurada.",
)

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def extract_job_id(key):
    """
    Espera key tipo 'inputs/<jobId>/submissions.csv'.
    Si no calza ese patron, usa el nombre del archivo sin extension.
    """
    parts = key.split("/")
    if len(parts) >= 3 and parts[0] == "inputs":
        return parts[1]
    return parts[-1].rsplit(".", 1)[0]


def handler(event, context):
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        job_id = extract_job_id(key)

        obj = s3.get_object(Bucket=bucket, Key=key)
        # utf-8-sig por si el CSV viene de Excel con BOM
        text = obj["Body"].read().decode("utf-8-sig")

        # La rubrica la fija la API en el item META (camino normal del frontend).
        # Fallback: metadata de S3 (prueba por CLI) o la rubrica por defecto.
        existing = table.get_item(Key={"PK": f"JOB#{job_id}", "SK": "META"}).get("Item") or {}
        rubrica = (
            existing.get("rubrica")
            or obj.get("Metadata", {}).get("rubrica")
            or DEFAULT_RUBRICA
        )
        created = existing.get("createdAt") or now_iso()

        reader = csv.DictReader(io.StringIO(text))
        rows = [r for r in reader if (r.get("id_estudiante") or "").strip()]

        # 1) Registro/actualizacion del META del job (preserva createdAt)
        table.put_item(
            Item={
                "PK": f"JOB#{job_id}",
                "SK": "META",
                "status": "PROCESSING",
                "total": len(rows),
                "rubrica": rubrica,
                "createdAt": created,
                "updatedAt": now_iso(),
            }
        )

        # 2) Crear items PENDING (batch_writer) y juntar mensajes SQS
        sqs_entries = []
        with table.batch_writer() as bw:
            for i, row in enumerate(rows):
                sid = row["id_estudiante"].strip()
                texto = (row.get("texto_entrega") or "").strip()

                bw.put_item(
                    Item={
                        "PK": f"JOB#{job_id}",
                        "SK": f"ITEM#{sid}",
                        "status": "PENDING",
                        "id_estudiante": sid,
                        "createdAt": now_iso(),
                        "updatedAt": now_iso(),
                    }
                )

                sqs_entries.append(
                    {
                        "Id": str(i),  # unico dentro de cada send_message_batch
                        "MessageBody": json.dumps(
                            {
                                "jobId": job_id,
                                "idEstudiante": sid,
                                "texto": texto,
                                "rubrica": rubrica,
                            }
                        ),
                    }
                )

        # 3) Enviar a SQS en lotes de 10 (limite de send_message_batch)
        for batch in _chunks(sqs_entries, 10):
            # reindexar Id 0..9 dentro de cada request (deben ser unicos por request)
            for n, entry in enumerate(batch):
                entry["Id"] = str(n)
            sqs.send_message_batch(QueueUrl=QUEUE_URL, Entries=batch)

        print(f"Job {job_id}: {len(rows)} entregables encolados.")

    return {"ok": True}


def _chunks(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]
