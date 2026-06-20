# Servicio RAG de RúbricaIA (FastAPI + FastEmbed). Imagen multi-arch: corre en
# ARM (Ampere/A2.Flex de OCI) y en x86.
FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema:
#  - libgomp1: runtime de onnxruntime (lo usa FastEmbed).
#  - build-essential: compilador C. FastEmbed depende de PyStemmer, que en ARM
#    no trae wheel precompilado y se compila desde fuente (necesita gcc).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
