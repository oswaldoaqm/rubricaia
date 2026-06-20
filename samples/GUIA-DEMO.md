# Guía de la demo — material de prueba calibrado

Set de 12 "estudiantes" en formatos mixtos (PDF, Word, TXT), cada uno escrito para
sacar un **porcentaje conocido** contra una rúbrica concreta. Úsalo para grabar el video:
subes el trabajo de un alumno y el sistema devuelve **exactamente** el % esperado.

---

## 1. La tarea que debe crear el profesor

**Título sugerido:** `Propuesta de proyecto de innovación`

**Rúbrica** — pega estos 5 criterios (uno por línea) en el campo de rúbrica de la tarea:

```
1. Define un problema real y concreto, respaldado con datos o cifras.
2. Identifica claramente al usuario afectado por el problema.
3. Describe la solución y su caso de uso paso a paso.
4. Justifica el impacto esperado con métricas concretas y medibles.
5. Redacción clara y estructurada (introducción, desarrollo y conclusión).
```

**Pesos por criterio** (deben sumar 100, en el mismo orden):

| Criterio | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Peso | **25** | **20** | **20** | **25** | **10** |

> Importante: el número y el orden de los criterios de la rúbrica deben coincidir con
> los pesos. El Worker deriva el % de forma **ponderada** con estos pesos; si no pones
> pesos, lo calcula equitativo (cada criterio vale 20%).

---

## 2. Tabla de respuestas (lo que debe sacar cada estudiante)

`✓` = el texto cumple el criterio · `✗` = no lo cumple. El % es la suma de los pesos
de los criterios cumplidos.

| Estudiante | Archivo | C1 | C2 | C3 | C4 | C5 | **% esperado** |
|---|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Ana Torres | `ana.pdf` | ✓ | ✓ | ✓ | ✓ | ✓ | **100 %** |
| Bruno Díaz | `bruno.docx` | ✓ | ✓ | ✓ | ✓ | ✗ | **90 %** |
| Karla Mendoza | `karla.docx` | ✓ | ✓ | ✗ | ✓ | ✓ | **80 %** |
| Carla Ríos | `carla.txt` | ✓ | ✓ | ✓ | ✗ | ✓ | **75 %** |
| Diego Salas | `diego.pdf` | ✓ | ✓ | ✗ | ✓ | ✗ | **70 %** |
| Mónica León | `monica.docx` | ✓ | ✓ | ✓ | ✗ | ✗ | **65 %** |
| Felipe Ramos | `felipe.txt` | ✓ | ✗ | ✗ | ✓ | ✓ | **60 %** |
| Elena Vega | `elena.docx` | ✓ | ✓ | ✗ | ✗ | ✓ | **55 %** |
| Gabriela Soto | `gabriela.pdf` | ✓ | ✓ | ✗ | ✗ | ✗ | **45 %** |
| Hugo Castro | `hugo.txt` | ✓ | ✗ | ✗ | ✗ | ✓ | **35 %** |
| Inés Flores | `ines.txt` | ✓ | ✗ | ✗ | ✗ | ✗ | **25 %** |
| Javier Peña | `javier.pdf` | ✗ | ✗ | ✗ | ✗ | ✗ | **0 %** |

**Promedio de la clase ≈ 58 %.** Distribución: alto (≥70%) = 5 · medio (40–70%) = 4 ·
bajo (<40%) = 3. El criterio que más falla la clase es **C3 (caso de uso paso a paso)**,
seguido de **C4 (impacto con métricas)** — útil para mostrar el panel de insights.

> Los textos están escritos para que cada criterio sea **inequívoco** (claramente
> presente o ausente), así el LLM marca lo esperado. Puede haber ±1 criterio de
> variación en algún caso límite; si quieres el 100% perfecto en cámara, usa **Ana**
> (todo presente) vs **Javier/Inés** (casi nada) para el contraste más limpio.

---

## 3. Qué subir en el video

- **Contraste claro (recomendado):** sube `ana.pdf` → **100 %**, y luego `javier.pdf`
  → **0 %** o `ines.txt` → **25 %**. La diferencia se ve de inmediato.
- **Mostrar formatos:** sube uno de cada tipo (un `.pdf`, un `.docx`, un `.txt`) para
  evidenciar que acepta PDF, Word y texto.
- **Lote masivo (criterio 3) por CLI:** usa `samples/clase-demo.csv` (12 filas) para la
  prueba por terminal del manual; verás el panel de insights del profesor poblado con la
  clase entera.

---

## 4. El profesor sí ve el trabajo subido

Lo que sube el alumno **se guarda y queda accesible** para el profesor / evaluador:

- El texto del entregable se almacena en **S3** como `inputs/<jobId>/submissions.csv`
  (en el bucket `rubricaia-inputs-<acct>-dev`) y en **DynamoDB** (`rubricaia-dev`, item
  `ITEM#<id>`, atributo `texto`).
- Desde la vista del profesor ("Entregas" de la tarea) ve el cumplimiento de cada alumno
  y puede abrir su resultado; el contenido entregado se puede recuperar por la API
  (`GET /jobs/{jobId}`) o directamente del CSV en S3.

```bash
# Ver lo que entregó un alumno (texto + evaluación) desde la API:
curl -s "<API_URL>/jobs/<jobId>" | python3 -m json.tool
# O descargar el archivo que llegó a S3:
aws s3 cp "s3://rubricaia-inputs-334461248248-dev/inputs/<jobId>/submissions.csv" -
```

> Nota: el **texto** del entregable se archiva (extraído en el navegador). El binario
> original (PDF/Word) no se guarda en el servidor; si quisieras archivar también el
> binario, es una mejora pequeña de la API (subir el archivo además del CSV).

---

## 5. Archivos generados

```
samples/
├── GUIA-DEMO.md            # este archivo
├── clase-demo.csv          # lote de 12 entregables (id_estudiante, texto_entrega)
└── estudiantes/
    ├── ana.pdf        (100%)   ├── monica.docx   (65%)
    ├── bruno.docx     (90%)    ├── felipe.txt    (60%)
    ├── karla.docx     (80%)    ├── elena.docx    (55%)
    ├── carla.txt      (75%)    ├── gabriela.pdf  (45%)
    ├── diego.pdf      (70%)    ├── hugo.txt      (35%)
    ├── ines.txt       (25%)    └── javier.pdf    (0%)
```
