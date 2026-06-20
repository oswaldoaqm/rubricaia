# RúbricaIA - Servicio RAG en OCI (multinube)

Componente **multinube**: corre en una VM de **Oracle Cloud (OCI)** y enriquece la
evaluación del LLM con material del curso recuperado de una base vectorial.

- **Qdrant** — base de datos vectorial (interna, no expuesta).
- **Servicio RAG** (FastAPI + FastEmbed) — embeddings + búsqueda; expone el puerto `8000`.

El Worker de AWS Lambda llama `POST /retrieve` con el texto del entregable y recibe los
fragmentos más relevantes para inyectarlos en el prompt de Groq. Si OCI no responde, el
Worker evalúa igual (degradación elegante).

## Despliegue en la VM de OCI

> Reusa la VM del laboratorio (compartment `lab-oci`, VCN `vcn-lab`, Oracle Linux, ARM).
> En Oracle Linux `docker` es **podman** (funciona igual).

### 1. Abrir el puerto 8000 (dos capas de firewall)

- **OCI Security List** (VCN `vcn-lab` → Security → Default Security List → Add Ingress Rule):
  `Source 0.0.0.0/0 · TCP · Destination port 8000`. (Si ya lo abriste en el lab, listo.)
- **Firewall del SO** en la VM:
  ```bash
  sudo firewall-cmd --permanent --add-port=8000/tcp
  sudo firewall-cmd --reload
  ```

### 2. Instalar Docker (si no está) y clonar el repo

```bash
sudo dnf install docker git -y
git clone https://github.com/oswaldoaqm/rubricaia.git
cd rubricaia/oci-rag
```

### 3. Levantar el stack

Con compose (si tienes `docker compose` / `podman compose`):
```bash
docker compose up -d --build
```

O manual (equivalente, estilo del laboratorio con podman):
```bash
docker network create ragnet
docker run -d --name qdrant --network ragnet -v qdrant_data:/qdrant/storage qdrant/qdrant
docker build -t rag-service .
docker run -d --name rag --network ragnet -p 8000:8000 \
  -e QDRANT_URL=http://qdrant:6333 -e EMBED_MODEL=intfloat/multilingual-e5-large rag-service
```

La primera vez, el servicio descarga el modelo de embeddings (~100 MB) y siembra material
de referencia por criterio.

### 4. Verificar

```bash
# en la VM:
curl http://localhost:8000/health
# desde tu equipo (usa la IP pública de la VM):
curl http://<IP-PUBLICA>:8000/health
curl -X POST http://<IP-PUBLICA>:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"text":"mi proyecto reduce la desercion en 15%","k":3}'
```

`/health` debe devolver `{"ok": true, ... "count": N}` y `/retrieve` una lista de
`contexts`. Cuando funcione, pásame la **IP pública** para conectar el Worker
(variable `RAG_URL` en el backend de AWS).

## Ingestar material propio (opcional)

```bash
curl -X POST http://<IP-PUBLICA>:8000/ingest -H "Content-Type: application/json" \
  -d '{"docs":[{"text":"<fragmento del sílabo o ejemplo de buena entrega>","meta":{"fuente":"silabo"}}]}'
```

## Seguridad (demo)

El puerto 8000 queda abierto a `0.0.0.0/0` para la demo. Para producción se restringiría
el origen (solo NAT/IP de AWS) o se añadiría un API key. Qdrant nunca se expone.
