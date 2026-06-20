# Contexto de la problemática e impacto

## El problema

En los cursos universitarios, los estudiantes entregan trabajos y proyectos académicos
(propuestas, informes, ensayos) que se califican contra una **rúbrica**. Pero existe una
brecha que afecta a ambos lados del aula:

- **El estudiante entrega a ciegas.** No sabe con certeza si su trabajo cumple cada
  criterio de la rúbrica *antes* de la entrega final. Descubre qué le faltaba recién
  cuando recibe la nota, cuando ya no puede corregir.
- **El docente no da abasto.** Revisar a fondo cada versión preliminar de cada estudiante
  para dar retroalimentación temprana es inviable con 30, 60 o 120 alumnos. La
  retroalimentación llega tarde, es desigual, o simplemente no llega.

El resultado: los estudiantes pierden la oportunidad de mejorar a tiempo y los docentes
se saturan haciendo una tarea repetitiva y mecánica (verificar criterio por criterio)
que les roba horas que podrían dedicar a la enseñanza de fondo.

## Quién se ve afectado

- **Estudiante (usuario principal):** quiere saber, antes de entregar, si cumple la
  rúbrica y qué corregir.
- **Docente:** necesita escalar la retroalimentación temprana a *toda* la clase sin
  ahogarse, y ver de un vistazo dónde está fallando el grupo.

## La solución: RúbricaIA

RúbricaIA es una plataforma donde el docente crea sus **clases** y **tareas** (cada una
con su rúbrica y, opcionalmente, pesos por criterio y fecha límite), e invita a sus
estudiantes. El estudiante sube su entregable en **PDF o Word**, y un **LLM (vía Groq)**
lo revisa **criterio por criterio** contra la rúbrica de esa tarea, devolviendo:

- un **porcentaje de cumplimiento** derivado de los criterios cumplidos,
- la evaluación **criterio por criterio** (cumple / no cumple, con evidencia citada),
- **sugerencias concretas y accionables** para mejorar cada criterio no cumplido.

El docente, por su parte, ve las **entregas de toda la clase** por tarea: quién entregó,
su cumplimiento, el **promedio y la distribución del grupo**, y los **criterios que más
falla la clase** — la información exacta para intervenir donde duele.

## Por qué un LLM aporta valor real aquí

Evaluar un texto libre contra criterios cualitativos ("¿define un problema real y
concreto?", "¿justifica el impacto con métricas?") **no es un problema de reglas ni de
keywords**: requiere comprensión semántica del contenido. Un LLM:

- entiende el texto del estudiante y lo **contrasta con cada criterio**, citando la
  evidencia que justifica su juicio;
- genera **retroalimentación redactada y específica** ("agrega 2-3 métricas de éxito como
  % de reducción de deserción"), no un puntaje opaco;
- **escala**: la misma calidad de revisión para 1 o para 120 entregas, en paralelo.

Es exactamente el tipo de tarea —juicio cualitativo, repetitivo y a gran escala— donde un
LLM multiplica la capacidad del docente en lugar de reemplazar su criterio.

## Casos de uso

1. **Autoevaluación temprana del estudiante.** Antes de la entrega final, el alumno sube
   su borrador y recibe su cumplimiento y faltantes; corrige y reentrega cuantas veces
   quiera.
2. **Retroalimentación masiva del docente.** El profesor abre una tarea y obtiene la
   foto de toda la clase: promedio, distribución y criterios más fallados, para reforzar
   en la siguiente sesión lo que el grupo no está logrando.
3. **Detección de coincidencias.** El sistema marca pares de entregas sospechosamente
   similares (TF-IDF + coseno) como señal temprana de posible copia.

## Impacto esperado

- **Retroalimentación temprana y equitativa** para *todos* los estudiantes, no solo los
  que el docente alcanza a revisar.
- **Ahorro de tiempo docente** en la verificación mecánica criterio-por-criterio, que se
  automatiza, liberando horas para la enseñanza.
- **Mejora medible de los entregables finales**: el estudiante itera con feedback objetivo
  antes de la nota, lo que se traduce en mayor cumplimiento de la rúbrica en la entrega
  final y, potencialmente, en menor reprobación.
- **Decisiones basadas en datos**: el docente ve patrones de toda la clase (p. ej. "el
  80% falla en justificar el impacto con métricas") y ajusta su enseñanza.

## Alcance técnico (resumen)

El foco del reto no es solo invocar el modelo, sino la **arquitectura basada en eventos,
asíncrona y serverless**. RúbricaIA procesa los entregables en **lotes controlados de
20–30**, con **resiliencia ante los límites de la API del LLM** (reintentos por cola con
backoff, DLQ, idempotencia) y un **plano de control multi-tenant** (autenticación,
clases, tareas, membresías) claramente separado del **plano de datos event-driven**. El
diseño completo está en [`docs/arquitectura.svg`](./arquitectura.svg) y el detalle de
despliegue en [`docs/manual-despliegue.md`](./manual-despliegue.md).
