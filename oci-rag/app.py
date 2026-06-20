"""
RúbricaIA - Servicio RAG (corre en la VM de OCI, multinube)
===========================================================
Microservicio que da soporte de Retrieval-Augmented Generation:
  - Embeddings con FastEmbed (ONNX, CPU/ARM; ligero, sin torch).
  - Base vectorial Qdrant (en el mismo docker-compose, no expuesta a internet).
  - El Worker de AWS Lambda llama /retrieve con el texto del entregable y recibe
    los fragmentos de material del curso más relevantes para inyectarlos en el
    prompt de Groq.

Endpoints:
  GET  /health              -> estado + nº de documentos indexados
  POST /ingest {docs:[...]} -> indexa material de referencia (sílabo, ejemplos)
  POST /retrieve {text,k}   -> devuelve los k fragmentos más relevantes

Variables de entorno:
  QDRANT_URL   = http://qdrant:6333   (servicio interno del compose)
  EMBED_MODEL  = intfloat/multilingual-e5-small  (multilingüe, ideal español)
  COLLECTION   = rubricaia
"""

import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "intfloat/multilingual-e5-small")
COLLECTION = os.environ.get("COLLECTION", "rubricaia")

app = FastAPI(title="RubricaIA RAG service")
embedder = TextEmbedding(model_name=EMBED_MODEL)
DIM = len(list(embedder.embed(["sonda de dimension"]))[0])
qdrant = QdrantClient(url=QDRANT_URL)

# Material de referencia mínimo: guía por criterio. Se indexa al arrancar si la
# colección está vacía, para que /retrieve devuelva algo útil desde el primer uso.
SEED = [
    {"text": "Un buen planteamiento define un problema concreto y medible, no una "
             "generalidad. Ejemplo fuerte: 'la deserción en primer ciclo alcanza 22%'.",
     "meta": {"criterio": "problema"}},
    {"text": "Identificar al usuario afectado significa nombrar al actor concreto que "
             "sufre el problema (estudiantes de primer ciclo, docentes, etc.) y cómo le impacta.",
     "meta": {"criterio": "usuario"}},
    {"text": "Un caso de uso claro describe paso a paso cómo alguien usa la solución en "
             "una situación real, con un escenario concreto de inicio a fin.",
     "meta": {"criterio": "caso_de_uso"}},
    {"text": "Justificar el impacto con métricas implica incluir indicadores cuantificables: "
             "% de mejora, reducción de tiempo, número de beneficiarios, antes/después.",
     "meta": {"criterio": "impacto"}},
    {"text": "Una redacción clara tiene introducción, desarrollo y conclusión, párrafos "
             "ordenados y lenguaje preciso, sin ser una lista suelta de ideas.",
     "meta": {"criterio": "redaccion"}},
]


def ensure_collection():
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION not in existing:
        qdrant.create_collection(
            COLLECTION, vectors_config=VectorParams(size=DIM, distance=Distance.COSINE)
        )


def embed(texts):
    return [list(map(float, v)) for v in embedder.embed(texts)]


def _ingest(items):
    texts = [it["text"] for it in items]
    vecs = embed(texts)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=v,
            payload={"text": it["text"], **it.get("meta", {})},
        )
        for v, it in zip(vecs, items)
    ]
    qdrant.upsert(COLLECTION, points=points)
    return len(points)


@app.on_event("startup")
def startup():
    ensure_collection()
    if qdrant.count(COLLECTION).count == 0:
        _ingest(SEED)


class Doc(BaseModel):
    text: str
    meta: dict = {}


class IngestReq(BaseModel):
    docs: list[Doc]


class RetrieveReq(BaseModel):
    text: str
    k: int = 3


@app.get("/health")
def health():
    return {"ok": True, "model": EMBED_MODEL, "dim": DIM, "count": qdrant.count(COLLECTION).count}


@app.post("/ingest")
def ingest(req: IngestReq):
    n = _ingest([{"text": d.text, "meta": d.meta} for d in req.docs])
    return {"ingested": n}


@app.post("/retrieve")
def retrieve(req: RetrieveReq):
    qv = embed([req.text])[0]
    hits = qdrant.search(collection_name=COLLECTION, query_vector=qv, limit=req.k)
    return {"contexts": [h.payload.get("text", "") for h in hits if h.payload]}
