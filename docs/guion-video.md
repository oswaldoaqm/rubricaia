# Guion del Video Demo — RúbricaIA (≤ 5 min)

> Objetivo: que el jurado vea **cada criterio de la rúbrica** reflejado, sin relleno.
> Graba en una sola toma o por secciones. Ten TODO abierto en pestañas antes de grabar.

## Antes de grabar — ten esto listo en pestañas/ventanas
1. El **diagrama** `docs/arquitectura.svg` abierto.
2. El **frontend** (Amplify): https://main.d2aurxjj1g5f03.amplifyapp.com — con una cuenta de **profesor** ya logueada en una pestaña y una de **alumno** en otra (o ventana incógnito).
3. Un **PDF/Word de prueba** para subir como alumno (uno bueno y uno flojo, para contraste).
4. Una terminal en la **VM de AWS** lista para: `aws logs tail /aws/lambda/rubricaia-dev-worker --since 2m --format short`.
5. Una terminal (tu PC) lista para el **curl al RAG de OCI** (multinube).
6. La consola de AWS abierta en **SQS** (cola + DLQ) y/o **CloudWatch**, por si muestras el reintento.

---

## Guion (tiempos aproximados)

### 0:00 – 0:30 · El problema (Criterio 1: Contexto e impacto)
Cámara a ti o a una slide simple. Di:
> "Los estudiantes entregan trabajos sin saber si cumplen la rúbrica, y los docentes no
> alcanzan a dar retroalimentación temprana a toda su clase. **RúbricaIA** resuelve esto:
> una IA revisa cada entrega contra la rúbrica de la tarea y devuelve, criterio por criterio,
> qué cumple, qué falta y cómo mejorar — antes de la entrega final."

### 0:30 – 1:15 · Arquitectura (Criterio 2: Diseño y diagrama)
Muestra `docs/arquitectura.svg`. Recorre los dos planos:
> "Tiene dos planos. Uno **síncrono** de control: frontend en Amplify → API Gateway → Lambdas
> de auth (JWT) y LMS (clases, tareas). Y uno **asíncrono y event-driven**, que es el corazón:
> la entrega va a **S3**, dispara un **Splitter** que encola en **SQS**, un **Worker** llama al
> **LLM (Groq)**, guarda en **DynamoDB**, y los **Streams** disparan un **Aggregator** que
> calcula estadísticas de la clase en vivo y, al cerrar el lote, emite un evento en
> **EventBridge** que hace fan-out a **SNS** (email al docente) y a una **Report Lambda**.
> Son **7 Lambdas**, todo **serverless** y declarado como **IaC en un solo `serverless deploy`**."

Recalca: "Basada en eventos, asíncrona, predominantemente serverless." (Las palabras exactas de la rúbrica.)

### 1:15 – 2:30 · Demo profesor + alumno (Criterios 4 y 3)
- Como **profesor**: crea (o muestra ya creada) una **clase** y una **tarea** con su rúbrica y
  pesos. Invita a un estudiante. Di una frase: "la rúbrica y los pesos los fija la tarea, no el alumno."
- Como **alumno**: acepta la invitación, abre la tarea, **sube un PDF**. Recalca:
  > "El texto se extrae en el navegador con pdf.js; sube cualquier PDF o Word."
- Mientras procesa, muestra la **terminal de AWS** con `aws logs tail ... worker` corriendo, para
  que se vea el procesamiento asíncrono real.
- Cuando termine, abre el **resultado del alumno**: el anillo de cumplimiento + la evaluación
  **criterio por criterio** (✓/✗, evidencia, sugerencia). Sube un segundo intento para mostrar
  el **historial de intentos** y la tendencia.

### 2:30 – 3:15 · Vista del profesor + insights (Criterio 4)
Vuelve a la cuenta de **profesor** → entra a la tarea → muestra **todas las entregas** con su
cumplimiento, y el panel de **insights de la clase**: promedio, distribución y **criterios más
fallados** de todo el curso.
> "Esto lo calcula el Aggregator en tiempo real vía DynamoDB Streams — el dato dispara el
> agregado, sin polling."

### 3:15 – 4:00 · Resiliencia (Criterio 3) — EL MOMENTO FUERTE
Este es el que más distingue tu proyecto. Demuestra el manejo de límites del LLM:
> "El sistema procesa en lotes y es resiliente a los límites de la API del LLM."
- Muestra en **SQS** la cola principal + la **DLQ**.
- Explica/muestra: ante un **429** de Groq, el Worker hace **backoff exponencial con Retry-After**
  y el mensaje vuelve a la cola; tras N intentos va a la **DLQ**; el estado de cada entregable
  queda visible (`RETRYING` / `FAILED`) y hay un botón de **reprocesar fallidos**. **Cero pérdida
  de datos**, idempotencia para no duplicar.
- (Si lo tienes preparado, fuerza un fallo y muestra el reintento en los logs.)

### 4:00 – 4:40 · Multinube OCI + RAG (Bonus)
> "Y vamos más allá de una sola nube. En una VM de **Oracle Cloud (OCI)** corre un servicio
> **RAG** —Qdrant + embeddings multilingües— que enriquece la evaluación con material del curso."
- En tu PC, ejecuta el `curl` en vivo y muestra que devuelve **contexto en español**:
  ```bash
  curl -X POST http://163.192.116.108:8000/retrieve -H 'Content-Type: application/json' \
    -d '{"text":"mi proyecto reduce la desercion estudiantil en 15%","k":3}'
  ```
- Muestra en el código del Worker la variable `RAG_URL` y la función `_retrieve_context`.
- Frase honesta y elegante:
  > "El Worker consulta este servicio en OCI antes de llamar al LLM; y si OCI no responde,
  > evalúa igual — **degradación elegante**. Multinube **AWS + OCI**, con resiliencia de extremo a extremo."

### 4:40 – 5:00 · Cierre (mapeo a la rúbrica)
Resume rápido, tocando los 5 criterios:
> "En resumen: un problema real con impacto claro; arquitectura 100% event-driven, asíncrona y
> serverless en IaC; procesamiento por lotes resiliente con reintentos y DLQ sin pérdida de datos;
> un frontend público multi-tenant con feedback por criterio; y un repo con manual y despliegue
> reproducible. Gracias."

---

## Reglas de oro para grabar
- **Habla los nombres de la rúbrica**: "basada en eventos", "asíncrona", "serverless",
  "lotes", "reintentos sin pérdida de datos", "URL pública". El jurado tacha su checklist.
- Si algo va lento (el LLM tarda), **edita/corta** — no dejes silencios largos.
- Ten un **lote de prueba ya procesado** de respaldo por si algo falla en vivo.
- Sube el video a **YouTube** (no listado está bien) y pega el link en el README.
- Dura ≤ 5 min: si te pasas, recorta la parte de creación de clase (muéstrala ya hecha).

## Checklist de evidencias a capturar (por si el jurado las pide)
- [ ] URL pública del frontend funcionando.
- [ ] Captura del dashboard del profesor con insights.
- [ ] Captura del resultado del alumno (criterio por criterio).
- [ ] Captura de la cola SQS + DLQ.
- [ ] Captura del `curl` al RAG de OCI devolviendo contexto (multinube).
- [ ] El repo con README + manual + diagrama.
