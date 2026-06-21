# Tarjeta rápida del video — RúbricaIA

Para tener de reojo mientras grabas. El detalle (comandos, qué decir) está en
`video-paso-a-paso.md`. Apunta a ~5 min. Habla con tus palabras, no leas.

## Ruta de la grabación

| Min | Qué muestras | Qué dices, en una línea |
|----|--------------|--------------------------|
| 0:00 | Tú / logo | El problema: entregar a ciegas; el profe sin tiempo. Lo resuelve una IA que revisa por criterios. |
| 0:30 | El diagrama | Dos partes: gestión síncrona, y la evaluación que va toda por eventos. 7 Lambdas, sin servidor, todo como código. |
| 1:20 | Frontend (profesor) | Creo clase y tarea con su rúbrica y pesos; invito al alumno. |
| 2:00 | Frontend (alumno) + logs | Subo un PDF; la página no espera. En la terminal se ve al worker procesando solo. |
| 2:45 | Resultado del alumno | Su porcentaje y la revisión criterio por criterio, con evidencia y sugerencias. Subo un 2.º intento → historial. |
| 3:10 | Frontend (profesor) "Entregas" | Promedio del grupo, distribución y criterios más fallados, en vivo. |
| 3:40 | Logs + cola DLQ | Rompo la clave a propósito → reintentos → cola de fallos. Restauro y reproceso. No se pierde nada. |
| 4:20 | OCI por SSH + código | Segunda nube: el servicio de RAG en Oracle Cloud, consultado en vivo. Si falla, evalúa igual. |
| 4:45 | — | Cierre: problema real, arquitectura por eventos serverless, resiliencia, frontend público, repo reproducible. |

## Tres recordatorios
- Lo que más pesa es la **Parte 4 y la Parte 6** (el backend asíncrono y los reintentos). Dales aire.
- No te pierdas creando clases en cámara: tenlas listas y solo haz **una** entrega nueva.
- La segunda nube, muéstrala desde la VM de OCI; si preguntan por el enlace AWS→OCI, dices la verdad: el lab limita ese tráfico, por eso el sistema está hecho para funcionar sin él.

## Antes de subir
URL del frontend OK · backend procesando (logs) · revisión por criterio · vista del profesor ·
reintentos/DLQ · RAG en OCI respondiendo. Luego: YouTube (no listado), enlace en el README,
regenera las claves.
