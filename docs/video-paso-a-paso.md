# Guía para grabar el video — RúbricaIA

Esto es para tenerlo al lado mientras grabas. Tres marcas:
**DECIR** = lo que cuentas (con tus palabras, no lo leas tal cual o sonará robótico),
**HACER** = lo que clicas o ejecutas, **VERÁS** = lo que debe salir en pantalla.
Apunta a unos 5 minutos; puedes grabar por partes y unirlas, y cortar las esperas.

Datos de tu despliegue (confírmalos en la preparación):
- Frontend: `https://main.d2aurxjj1g5f03.amplifyapp.com`
- API: `https://m0mx1jdgna.execute-api.us-east-1.amazonaws.com` (verifícalo con `serverless info`)
- Cuenta AWS `334461248248` · región `us-east-1` · stack `rubricaia-dev`
- Bucket `rubricaia-inputs-334461248248-dev`
- Colas `rubricaia-jobs-dev` y `rubricaia-dlq-dev`
- Lambdas `rubricaia-dev-{auth,lms,api,splitter,worker,aggregator,report}`
- Tablas `rubricaia-dev` y `rubricaia-lms-dev`
- RAG en OCI: `http://163.192.116.108:8000`

---

## Antes de grabar (deja todo listo, ~10 min)

No empieces a grabar hasta que esto funcione.

**Backend arriba** (en la VM de AWS):
```bash
cd ~/rubricaia
source deploy/env.sh
aws sts get-caller-identity     # que las credenciales del lab estén vivas
serverless info                 # copia el endpoint del API y revisa que estén las 7 funciones
```
Si el endpoint cambió, úsalo en los comandos de abajo.

**Frontend arriba:** abre `https://main.d2aurxjj1g5f03.amplifyapp.com`, debe cargar el login.
Si no, reconstruye con `bash deploy/deploy-frontend.sh`.

**RAG en OCI:** entra por SSH a la VM y prueba `curl -s http://localhost:8000/health`.
Debe responder algo como `{"ok":true, "model":"...", "count":...}`.

**Cuentas y archivos:**
- Dos sesiones del frontend: una con tu correo de profesor (el que está en `TEACHER_EMAILS`) y
  otra de alumno (otro correo `@utec.edu.pe`), en ventanas separadas (una en incógnito).
- Ten a la mano un par de archivos de `samples/estudiantes/`: por ejemplo `ana.pdf` (sale 100%)
  y `javier.pdf` (sale 0%). El contraste se ve solo.
- Ten ya creada una clase y una tarea con su rúbrica, para no perder tiempo en cámara.

**Ventanas abiertas:** frontend (profesor y alumno), el diagrama `docs/arquitectura.svg`,
una terminal en la VM de AWS para los logs, una terminal para OCI, y el editor con
`backend/lambdas/worker/worker_lambda.py`.

---

## Parte 1 — El problema (0:00–0:30)

**DECIR** (con tus palabras, algo así):
> "Hola, les presento RúbricaIA. La idea sale de algo que nos pasa siempre: uno entrega un
> trabajo sin saber si de verdad cumple la rúbrica, y el profesor no tiene tiempo de revisar
> borrador por borrador a toda la clase. Entonces hicimos una plataforma donde el alumno sube
> su trabajo y una IA lo revisa criterio por criterio contra la rúbrica: le dice qué cumplió,
> qué le falta y cómo mejorarlo, antes de la entrega final. Pero para este reto lo que más nos
> importaba no era el modelo en sí, sino la arquitectura de atrás: que sea por eventos,
> asíncrona y serverless. Eso es lo que les voy a mostrar."

---

## Parte 2 — Cómo está armado (0:30–1:20)

**HACER:** muestra `docs/arquitectura.svg` en pantalla y ve señalando con el cursor.

**DECIR:**
> "Por dentro hay dos partes. Una es la gestión —login, clases y tareas— que pasa por API
> Gateway a dos funciones, auth y lms, con una tabla en DynamoDB. Esa parte es síncrona.
>
> La otra, que es la evaluación, va toda por eventos. Cuando se sube un trabajo, el archivo
> cae en S3 y eso dispara una función, el splitter, que parte el lote en un mensaje por cada
> entregable y los mete a una cola SQS. De ahí los toma el worker, que llama al modelo de Groq
> y guarda el resultado en DynamoDB. Cada vez que se guarda algo, los Streams de DynamoDB
> despiertan a otra función, el aggregator, que va armando las estadísticas de la clase; y
> cuando el lote termina, lanza un evento a EventBridge, que avisa al profesor por correo con
> SNS y arma un reporte. Son siete funciones Lambda, sin ningún servidor encendido, y todo
> está escrito como código en un solo archivo: con un comando se levanta entero."

**HACER** (opcional, 3s): pasa rápido por `serverless.yml`.

---

## Parte 3 — El profesor crea la tarea (1:20–2:00)

**HACER:** en la sesión de profesor, entra a una clase y muestra una tarea ya creada
(título, rúbrica, pesos, fecha).

**DECIR:**
> "Como profesor armo una clase y una tarea con su rúbrica y, si quiero, le pongo pesos a cada
> criterio. Invito a mis alumnos por correo, y ellos tienen que aceptar la invitación para
> entrar. Una cosa importante: la rúbrica la define la tarea, no el alumno."

---

## Parte 4 — El alumno entrega y se ve el backend trabajando (2:00–3:10)

Esta es la parte central: subes una entrega y a la vez muestras que el backend la procesa por
su cuenta.

**HACER:** antes de subir, en la terminal de la VM deja corriendo el log del worker:
```bash
aws logs tail /aws/lambda/rubricaia-dev-worker --follow --format short
```
**HACER:** en la sesión de alumno, abre la tarea y sube `ana.pdf` (o `javier.pdf`).

**DECIR:**
> "Entro como alumno y subo mi trabajo en PDF. El texto se extrae en el mismo navegador. Y
> fíjense que la página no se queda esperando al servidor."

**HACER:** mientras aparece "Evaluando…", cámbiate a la terminal del log.

**VERÁS:** líneas de la invocación del worker (START / END / REPORT).

**DECIR:**
> "Lo que pasó es que el archivo se subió a S3, eso disparó el splitter, se encoló en SQS, y el
> worker está procesando por su cuenta, llamando al modelo y guardando el resultado. Nada de
> esto bloqueó al usuario."

**HACER** (opcional, queda bien): muestra el dato real con la API. Saca el último job y consúltalo:
```bash
aws dynamodb scan --table-name rubricaia-dev \
  --filter-expression "SK = :m" --expression-attribute-values '{":m":{"S":"META"}}' \
  --query 'Items[].PK.S' --output text
# toma uno y (sin el prefijo JOB#):
curl -s "https://m0mx1jdgna.execute-api.us-east-1.amazonaws.com/jobs/<jobId>" | python3 -m json.tool
```
**VERÁS:** el JSON con `status: DONE`, el `cumplimiento` y la lista `criterios` (cada uno con
cumple, evidencia y sugerencia).

**HACER:** vuelve al frontend del alumno, que ya muestra su resultado.

**DECIR:**
> "Y acá lo ve el alumno: su porcentaje y la revisión criterio por criterio, con la evidencia y
> una sugerencia concreta para cada cosa que le faltó."

**HACER:** sube una segunda versión del mismo alumno y muestra el historial de intentos y cómo
cambia el cumplimiento entre uno y otro.

---

## Parte 5 — La vista del profesor (3:10–3:40)

**HACER:** cámbiate a la sesión de profesor, entra a la tarea y abre "Entregas".

**DECIR:**
> "El profesor ve todas las entregas de la clase: quién entregó, su cumplimiento, el promedio
> del grupo, cómo se reparten las notas y qué criterios falla más la clase. Todo eso se calcula
> en vivo a medida que entran los resultados. Con esto sabe dónde reforzar."

**HACER** (opcional): descarga el reporte de la clase.

---

## Parte 6 — Qué pasa cuando el modelo falla (3:40–4:20)

Acá muestras que el sistema aguanta los límites de la API sin perder datos. Hazlo con la versión
segura (guarda y restaura la clave). Si prefieres no tocar nada en vivo, usa la Opción B.

### Opción A — provocar el fallo en vivo
**HACER:** en la terminal, pon a propósito una clave inválida en el worker (guardando antes la buena):
```bash
aws lambda get-function-configuration --function-name rubricaia-dev-worker \
  --query 'Environment' --output json > /tmp/wenv.json
python3 - <<'PY'
import json
e=json.load(open('/tmp/wenv.json')); e['Variables']['GROQ_API_KEY']='gsk_INVALIDA_DEMO'
json.dump(e,open('/tmp/wenv_bad.json','w'))
PY
aws lambda update-function-configuration --function-name rubricaia-dev-worker \
  --environment file:///tmp/wenv_bad.json >/dev/null && echo "clave rota (a propósito)"
```
**HACER:** sube otra entrega y mira el log:
```bash
aws logs tail /aws/lambda/rubricaia-dev-worker --since 2m --format short
```
**VERÁS:** errores y reintentos; en el frontend el entregable queda en `RETRYING` y luego `FAILED`.

**DECIR:**
> "Cuando el modelo nos corta por límite de peticiones, el worker no pierde el dato: captura el
> error, espera un poco con un backoff y vuelve a encolar el mensaje. Después de tres intentos,
> ese mensaje se va a una cola aparte, la dead letter queue."

**HACER:** muestra la DLQ con mensajes:
```bash
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name rubricaia-dlq-dev --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages
```
**VERÁS:** `ApproximateNumberOfMessages` mayor que cero.

**DECIR:**
> "Ahí están los que fallaron, intactos. No se perdió nada."

**HACER:** restaura la clave buena y reprocesa:
```bash
aws lambda update-function-configuration --function-name rubricaia-dev-worker \
  --environment file:///tmp/wenv.json >/dev/null && echo "clave restaurada"
```
Luego en el frontend pulsa "Reprocesar fallidos".

**DECIR:**
> "Restauro el servicio y con un botón vuelvo a procesar los que habían fallado; ahora sí se
> evalúan bien."

### Opción B — sin tocar nada
**HACER:** muestra el código del worker (`worker_lambda.py`) y señala el manejo del 429 con
`Retry-After`, el `_compute_backoff` y el `batchItemFailures`. Luego muestra la política de la cola:
```bash
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name rubricaia-jobs-dev --query QueueUrl --output text)" \
  --attribute-names RedrivePolicy
```
**DECIR:** explica lo mismo con el código a la vista (reintentos con espera, la cola de fallos
después de 3 intentos, y que un mensaje ya procesado no se vuelve a procesar).

---

## Parte 7 — La segunda nube (4:20–4:45)

**HACER:** en la VM de OCI (por SSH), consulta el servicio en vivo:
```bash
curl -s -X POST http://localhost:8000/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"text":"mi proyecto reduce la desercion estudiantil en 15%","k":3}'
```
**VERÁS:** un JSON con `contexts` (fragmentos de material del curso, en español).

**DECIR:**
> "Una cosa más: no nos quedamos en una sola nube. En una máquina de Oracle Cloud levantamos un
> servicio de RAG —una base vectorial con embeddings— que el worker consulta para apoyar la
> evaluación con material del curso. Acá lo estoy consultando en vivo y me devuelve los
> fragmentos relevantes. Y está hecho para que, si esa nube no responde, la evaluación siga
> igual; no depende de ella."

**HACER:** muestra en `worker_lambda.py` la función `_retrieve_context` y la variable `RAG_URL`.

> Para ti (no lo digas en cámara): el servicio en OCI es real y está integrado; el tráfico
> directo AWS→OCI lo limita el Learner Lab, por eso lo enseñas desde la propia VM y por eso el
> worker está diseñado para funcionar igual sin él. Si te preguntan, eso es lo que respondes.

---

## Parte 8 — Cierre (4:45–5:00)

**DECIR:**
> "Para cerrar: es un problema real resuelto con un LLM donde de verdad aporta; una arquitectura
> por eventos, asíncrona y serverless, toda escrita como código; un procesamiento por lotes que
> aguanta los límites del modelo sin perder datos; un frontend público donde el alumno y el
> profesor ven todo; y un repositorio con su manual y su diagrama, que cualquiera puede levantar
> con un comando. Gracias por su tiempo."

---

## Antes de subir el video, revisa que se vea:
- La URL pública del frontend funcionando.
- El backend trabajando por su cuenta (los logs del worker o el resultado por la API).
- La revisión criterio por criterio y la vista del profesor con las estadísticas.
- Qué pasa cuando algo falla (los reintentos y la cola de fallos).
- El servicio de la segunda nube respondiendo.

Y antes de entregar: súbelo a YouTube (puede ser no listado), pega el enlace en el README, y
regenera las claves (`GROQ_API_KEY` y `SERVERLESS_ACCESS_KEY`).
