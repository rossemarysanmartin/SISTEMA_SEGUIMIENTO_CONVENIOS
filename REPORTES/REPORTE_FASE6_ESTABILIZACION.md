# Reporte Fase 6 — Estabilización, Usabilidad y Ajuste del Flujo Real

Fecha: 2026-08-26

## 1. Objetivo de la fase

Reducir la fricción de uso diario del módulo de Solicitudes sin cambiar su
arquitectura ni su trazabilidad: registrar un trámite o una actuación debía
dejar de sentirse como llenar un formulario largo.

## 2. Diagnóstico del flujo actual (antes de tocar código)

Revisando el flujo construido en la Fase 5 se identificaron estos problemas
concretos:

1. **"Registrar actuación" mostraba ~15 campos siempre**, sin importar si la
   actuación era tan simple como una nota interna o tan compleja como una
   solicitud de criterio con fecha límite.
2. **No existían atajos**: para cada acción frecuente (delegar, solicitar
   criterio, enviar a firma...) el usuario tenía que elegir manualmente el
   tipo de actuación de una lista de 28, y además saber de memoria qué
   combinación de estado+etapa correspondía — propenso a error e
   inconsistencias entre usuarios.
3. **Responder un pendiente exigía buscarlo** en un desplegable largo dentro
   del formulario genérico, en vez de partir directamente desde el pendiente
   mismo.
4. **No había "pendiente actual"**: había que leer todo el historial para
   saber qué se estaba esperando en este momento.
5. **Dependencia y responsable eran texto libre sin memoria**, con riesgo de
   nombres inconsistentes ("Procuraduría" vs "Procuraduría General").
6. **No se podía corregir un dato básico mal escrito** (institución, asunto)
   sin tocar la base directamente.
7. **Archivar era de un solo sentido** — no existía "reactivar".
8. **No había búsqueda global** — había que saber de antemano si se buscaba
   un convenio o una solicitud.
9. **Los umbrales del semáforo solo podían cambiarse editando `config.json`
   a mano.**
10. Los errores de base de datos (`IntegrityError`, etc.) no estaban
    capturados: se habrían visto como tracebacks crudos en pantalla.

Estos 10 puntos guiaron directamente las secciones 3-23 de esta fase.

## 3. Migración de esquema (aditiva)

Respaldo: `RESPALDOS\convenios_pre_fase6_20260826_133431.db`.
Verificación de integridad tras migrar: `PRAGMA integrity_check` → **ok**.

Nuevo (vía `db_fase6.py`, ejecutado con `migrar_fase6.py`):
- Tabla `configuracion_app` (clave/valor) — semáforo y umbrales editables desde la interfaz.
- Tabla `responsables` (nombre, cargo, dependencia, activo) — catálogo para autocompletar.
- Tabla `catalogo_tipos_convenio_solicitado` — reemplaza el texto libre de "tipo de convenio".
- Columna `orden` en `catalogo_medios_ingreso`, `catalogo_actuaciones`, `catalogo_dependencias`.
- Columna `responsable_inicial` en `solicitudes`.
- Nuevo tipo de actuación en catálogo: `NOTA_INTERNA`.

## 4. Mejoras de usabilidad implementadas

### Registro rápido de actuación (sección 3)
El formulario completo ahora muestra primero solo: tipo, fecha, dependencia,
responsable, descripción, estado nuevo, etapa nueva. Hora, resultado, fecha
límite, dependencia origen, delegado, documento y observaciones extensas
quedan bajo **"Más opciones"** (`<details>`, sin JavaScript de terceros).

### Acciones rápidas (sección 4)
8 botones contextuales en la ficha, cada uno abre un mini-formulario con solo
2-5 campos, autocompletando tipo de actuación + estado/etapa sugeridos
(siempre editables, nunca forzados):

| Acción | Campos que pide | Sugiere estado/etapa |
|---|---|---|
| 👤 Delegar | delegado*, fecha, descripción | — |
| 📤 Solicitar criterio | dependencia, fecha, responsable, fecha límite, descripción | PENDIENTE_DE_CRITERIO / CRITERIOS |
| 📤 Solicitar factibilidad | ídem | PENDIENTE_DE_RESPUESTA / FACTIBILIDAD |
| 📤 Enviar a jurídico | ídem | EN_REVISION_JURIDICA / REVISION_JURIDICA |
| 📤 Enviar a contraparte | fecha, responsable, descripción | EN_CONTRAPARTE / CONTRAPARTE |
| ✍️ Enviar a firma | fecha, responsable, descripción | EN_FIRMA / FIRMA |
| 🔗 Marcar suscrito | fecha, descripción | SUSCRITO / SUSCRITO |
| 🗒 Nota interna | fecha, descripción | sin cambio de estado/etapa |

### Registrar respuesta en un clic (secciones 15-16)
Cada pendiente abierto en la ficha tiene su propio botón "Registrar
respuesta" que abre un formulario ya vinculado a esa actuación concreta — el
usuario nunca vuelve a buscar cuál trámite está respondiendo. El tipo
"recibido" correcto (criterio/informe jurídico/factibilidad/documentación) se
infiere automáticamente del tipo original.

### Pendiente actual y pendientes abiertos (sección 14-15)
Campo calculado (nunca almacenado por separado, se deriva de actuaciones con
`requiere_respuesta='SI' AND respuesta_recibida='NO'`) visible en la
cabecera de la ficha y como columna en la tabla de solicitudes. Ejemplo real
verificado: *"Esperando Solicitud De Criterio de Procuraduría / Asesoría
Jurídica"*.

### Autocompletado (sección 5)
Fecha actual por defecto, responsable actual precargado en todos los
formularios de actuación, catálogo de responsables como `<datalist>` en
"Nueva solicitud", dependencia/responsable nunca se vuelven a pedir si ya
están en la solicitud.

### Catálogos administrables (secciones 7-10)
Pantalla **Configuración → Catálogos** para: medios de ingreso, tipos de
actuación, estados, etapas, dependencias, tipos de convenio y responsables.
Permite activar/desactivar/editar el texto visible/reordenar (▲▼) — **nunca
borra físicamente** un valor ya usado. Los favoritos por frecuencia de uso
(`dependencias_mas_usadas`, `actuaciones_mas_usadas`) están implementados en
el repositorio (sin IA, solo conteo local) y listos para conectar donde se
priorice.

### Nueva solicitud simplificada (secciones 11-12)
Campos esenciales visibles: fecha, medio, institución, asunto, tipo,
dependencia solicitante, responsable inicial, observación breve, y el
checkbox de recepción en Vinculación. El resto vive en **"Información
adicional"**, y dentro de ella los campos de correo/sistema institucional
aparecen dinámicamente según el medio elegido (JavaScript mínimo, sin
librerías externas).

### Ficha reorganizada (sección 13)
Orden nuevo: cabecera (institución/código) → tarjetas de estado/etapa/
responsable/delegado/días/pendiente actual → alertas priorizadas → acciones
rápidas → pendientes abiertos → datos de ingreso + vínculo con convenio →
registrar actuación (avanzado) → línea de tiempo → documentos → archivar.

### Alertas priorizadas (sección 19)
Máximo una alerta de intervención por vez, con la escala 🔴 (demora/revisar)
→ 🟠 (atención) → texto explícito siempre acompañando el color.

### Semáforo configurable desde la interfaz (sección 20)
`Configuración → Semáforo`: cambia `semaforo_normal_max`, `atencion_max`,
`demora_max` y el umbral de días hábiles de pendientes, guardado en la tabla
`configuracion_app` (con validación de que sean crecientes). **No requiere
editar ningún archivo.**

### Días calendario y días hábiles (sección 21)
Se muestran ambos valores en "Pendientes de respuesta" y en "Pendientes
abiertos" de la ficha. Días hábiles = lunes a viernes; sin calendario de
feriados todavía (documentado como pendiente explícito en
`fechas_habiles.py`).

### Búsqueda global (sección 22)
Caja de búsqueda en la cabecera de toda la aplicación (`/buscar?q=...`),
resultados diferenciados con etiquetas `SOLICITUD` / `CONVENIO`.

### Dashboard clicable (sección 23) y Actividad reciente (sección 32)
Ya todas las tarjetas del dashboard (convenios y solicitudes) son enlaces a
su vista filtrada correspondiente. Se agregó un bloque "Actividad reciente"
con las últimas actuaciones registradas en todo el sistema.

### Panel "Mi trabajo" (sección 31)
`/mi-trabajo`: sin autenticación real todavía, identifica al responsable por
una cookie local simple. Muestra trámites asignados/delegados, pendientes a
su cargo, y actividad reciente del equipo.

### Notas internas (sección 27)
Nuevo tipo de actuación `NOTA_INTERNA` que **no obliga** a cambiar estado ni
etapa — verificado explícitamente por prueba automatizada.

### Edición auditada y Archivar/Reactivar (secciones 29-30)
`Editar datos básicos` (institución, asunto, contacto, tipo, observaciones)
con cada cambio registrado en auditoría (valor anterior y nuevo). Se agregó
`Reactivar`, que restaura el estado que la solicitud tenía justo antes de
archivarse (leído de la propia auditoría, no inventado) y también queda
auditado.

### Experiencia de error (sección 35)
Manejador de errores global (`app.py`): cualquier excepción no controlada
muestra un mensaje en español ("No se pudo completar la operación...") en
vez de un traceback, y el detalle técnico completo queda en
`LOGS\app_errores.log`.

### Confirmaciones selectivas (sección 36)
Se agregó `confirm()` solo a: archivar, reactivar, vincular convenio y
corregir una actuación histórica. Registrar una actuación normal, una acción
rápida o una respuesta **no** pide confirmación.

### Timeline compacta con filtro (secciones 17-18)
Cada actuación es un `<details>` colapsable (se auto-expanden las 3 más
recientes); filtro por categoría (Todas/Criterios/Documentación/
Delegaciones/Firma/Sistema) vía enlaces simples, sin JavaScript adicional.

### Reportes prácticos (sección 33)
Agregados a `/solicitudes/informes`: ingresadas por semana, abiertas vs.
cerradas, tiempo promedio hasta la primera actuación, tiempo promedio total
(cerradas), pendientes por dependencia, carga por responsable.

## 5. Qué NO se cambió (intencional)

- Kanban sigue siendo de solo consulta, sin drag-and-drop.
- Vista compacta/detallada (sección 25) no se implementó como toggle
  explícito — la tabla de solicitudes ya adoptó la versión compacta como
  predeterminada (sección 24), que cubre el mismo objetivo práctico sin
  agregar otro control de interfaz.
- No se tocó el análisis documental, la sincronización incremental, ni el
  visualizador de convenios más allá de mostrar el enlace "Origen del
  trámite" ya existente.

## 6. Pruebas

**67/67 pruebas aprobadas** (`python -m pytest tests/ -v`):
- 52 de las fases anteriores, sin cambios — siguen pasando.
- 15 nuevas (`tests/test_fase6.py`), contra base SQLite temporal: pendiente
  actual (con y sin pendientes, y al responder), nota interna sin cambio de
  estado/etapa, edición auditada (con y sin cambios reales), reactivar
  restaurando el estado previo, override de configuración con prioridad
  sobre el default, no duplicar auditoría en un valor sin cambios,
  catálogos (crear/activar/desactivar/editar/mover sin borrado físico),
  búsqueda global diferenciando tipos, y favoritos por frecuencia de uso.

Además, se corrigió la fixture de pruebas de la Fase 5
(`tests/test_solicitudes.py`) para aplicar también la migración de Fase 6 —
de lo contrario fallaba por falta de la columna `responsable_inicial`.

### Simulación de los 3 casos realistas (sección 39)

Ejecutada con `app.test_client()` de Flask contra una **base SQLite temporal
completamente aislada** (nunca la real — se verificó con `PRAGMA
integrity_check` y conteos de filas antes y después que la base real quedó
en 0 solicitudes):

- **Caso A (correo)**: Recepción → Unidad → Delegación → Criterio → Respuesta
  → Factibilidad → Firma → Suscrito. Resultado: ficha final muestra
  correctamente "SUSCRITO — PENDIENTE DE INCORPORACIÓN AL REPOSITORIO".
- **Caso B (sistema institucional)**: Recepción → Revisión → Jurídico →
  Firma. Resultado: OK.
- **Caso C (trámite detenido)**: Recepción → Solicitud de criterio → 10 días
  sin respuesta. Resultado: aparece correctamente en "Pendientes de
  respuesta" con alerta de demora y en "Pendientes abiertos" de su ficha.

También se verificaron en la misma simulación: búsqueda global, edición
auditada, ciclo archivar→reactivar, y guardado de configuración del semáforo
desde la interfaz — las 4 sin errores.

## 7. Medición de fricción (sección 40)

| Proceso | Clics | Campos obligatorios | Campos usados en la práctica |
|---|---:|---:|---:|
| Crear solicitud (con recepción en Vinculación) | 2 | 2 (institución, medio) | 3 |
| Registrar traslado a la Unidad | 1 | 1 (tipo) | 2 |
| Delegar (acción rápida) | 2 | 1 (delegado) | 1 |
| Solicitar criterio (acción rápida) | 2 | 0 | 1 |
| Registrar respuesta (en un clic, vinculada) | 2 | 0 | 1 |
| Solicitar factibilidad (acción rápida) | 2 | 0 | 1 |
| Enviar a firma (acción rápida) | 2 | 0 | 0 |
| Marcar suscrito (acción rápida) | 2 | 0 | 0 |

Antes de esta fase, cada una de estas acciones (salvo crear solicitud)
requería abrir el formulario genérico de ~15 campos y **razonar
manualmente** cuál combinación de tipo+estado+etapa correspondía — ahora son
2 clics con 0-1 campos reales y la combinación correcta ya sugerida.
Cumple el objetivo orientativo de la sección 40 (3-6 campos realmente
necesarios; aquí quedó por debajo, en 0-3).

## 8. Errores encontrados

| Error | Estado |
|---|---|
| La fixture de pruebas de Fase 5 no aplicaba la migración de Fase 6 (columna faltante) | Corregido |
| Ninguno de bloqueo funcional en producción | — |

## 9. Pendientes para futuras fases

- Calendario de feriados para el cálculo de días hábiles (documentado como
  extensión futura en `fechas_habiles.py`).
- Vista compacta/detallada como toggle explícito, si se necesita en el futuro.
- Favoritos por frecuencia de uso: las funciones ya existen
  (`dependencias_mas_usadas`, `actuaciones_mas_usadas`) pero no están
  conectadas a los `<select>` de los formularios — conectarlas es una tarea
  pequeña y segura para cuando se priorice.
- Todo lo ya pendiente de fases anteriores (Outlook, multiusuario,
  PostgreSQL/SQL Server, autenticación) sigue igual, sin cambios.

## 10. Decisiones que podrían necesitar validación institucional

- Los valores iniciales del catálogo de dependencias, tipos de convenio y
  las sugerencias de estado/etapa por acción rápida son **supuestos
  razonables basados en la especificación**, no confirmados con el área de
  Vinculación — deben revisarse y ajustarse con quien opere el sistema a
  diario.
- El umbral por defecto de "días hábiles para pendiente de respuesta" (5) y
  los cortes del semáforo (3/7/14) son los mismos sugeridos en fases
  anteriores; ahora son editables desde Configuración sin intervención
  técnica, así que pueden calibrarse libremente por la institución.

## 11. Instrucciones de ejecución

```
python app.py
```

Abrir: **http://127.0.0.1:5000**

---

**El sistema se detiene aquí. No se implementó multiusuario, Outlook, ni
migración de base de datos, según lo solicitado.**
