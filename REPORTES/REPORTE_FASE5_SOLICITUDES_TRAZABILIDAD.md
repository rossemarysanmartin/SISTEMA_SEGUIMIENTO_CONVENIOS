# Reporte Fase 5 — Módulo de Solicitudes y Trazabilidad

Fecha: 2026-08-26

## 1. Objetivo de la fase

Registrar y hacer seguimiento de las solicitudes de convenio **antes** de que
lleguen a suscribirse: recepción, traslados, delegaciones, solicitudes de
criterio/informe, respuestas, y su eventual vínculo con un convenio ya
suscrito del inventario. Ingreso manual; sin integración de correo/Outlook,
sin autenticación, sin flujo rígido obligatorio.

## 2. Migraciones realizadas

- Respaldo obligatorio antes de tocar el esquema:
  `RESPALDOS\convenios_pre_fase5_20260826_105448.db` (y una segunda pasada
  idempotente en `..._113747.db` al agregar `ruta_relativa`).
- Migración 100% aditiva (`db_fase5.py`, ejecutada vía `migrar_fase5.py`):
  ningún dato ni tabla de fases anteriores fue alterado o eliminado.
- Nueva columna en `convenios`: `id_solicitud_origen` (vínculo hacia la
  solicitud que dio origen al convenio, cuando aplica).

## 3. Tablas creadas

| Tabla | Propósito |
|---|---|
| `solicitudes` | Registro principal de cada trámite en curso |
| `actuaciones_solicitud` | Historial cronológico de actuaciones (la trazabilidad) |
| `documentos_tramite` | Documentos asociados a un trámite (ruta + ruta relativa, sin copiar archivos) |
| `contadores_solicitud` | Contador transaccional para el código correlativo por año |
| `catalogo_medios_ingreso`, `catalogo_actuaciones`, `catalogo_estados_solicitud`, `catalogo_etapas_solicitud`, `catalogo_dependencias` | Catálogos ampliables, precargados con los valores iniciales de la especificación |
| `auditoria` | Registro de cambios de estado/etapa/responsable/delegación/vinculación/archivado |

## 4. Código correlativo (`SOL-AAAA-NNNN`)

Generado en `services/repositorio_solicitudes.py::generar_codigo_solicitud`:
transaccional con `BEGIN IMMEDIATE` (bloquea la base durante la lectura +
incremento del contador) y, como segunda barrera, `codigo_solicitud` tiene
restricción `UNIQUE` en la tabla — si dos intentos concurrentes chocaran,
el segundo reintenta automáticamente en vez de fallar o duplicar. Probado con
5 hilos generando códigos simultáneamente contra el mismo archivo: 5 códigos
únicos, cero errores.

## 5. Pantallas creadas

| Pantalla | Ruta |
|---|---|
| 📩 Solicitudes (tarjetas + tabla + filtros + búsqueda) | `/solicitudes` |
| ➕ Nueva solicitud | `/solicitudes/nueva` |
| Ficha de solicitud (cabecera, estado, alertas, timeline, registrar actuación, documentos, vincular convenio) | `/solicitudes/<id>` |
| 🗂 Tablero Kanban por etapa (solo consulta) | `/solicitudes/tablero` |
| 📈 Informes (por mes, medio, responsable, estado, etapa) | `/solicitudes/informes` |
| ⏳ Pendientes de respuesta | `/pendientes-de-respuesta` |
| Dashboard actualizado con dos universos separados (Convenios suscritos / Solicitudes en trámite) | `/` |

Menú actualizado: Inicio · Convenios · 📩 Solicitudes · ⏳ Pendientes ·
Próximos a vencer · Vencidos · Revisión · Sincronización.

## 6. Pruebas

**52/52 pruebas aprobadas** (`python -m pytest tests/ -v`):
- 29 de la Fase 4 (visualizador de convenios) — **siguen pasando sin cambios**,
  confirmando que el módulo nuevo no rompió nada existente.
- 23 nuevas de la Fase 5, contra una **base SQLite temporal** (nunca la real):
  código correlativo (formato, independencia por año, concurrencia con 5
  hilos, anti-duplicado), creación de solicitud, recepción en Vinculación,
  traslado, delegación (con historial conservado), solicitud y respuesta de
  criterio, días sin movimiento, semáforo configurable, días hábiles,
  filtros, búsqueda insensible a mayúsculas, auditoría (cambio de estado y
  delegación), vinculación bidireccional con convenio, eliminación lógica
  (no física), corrección de actuación sin editar el historial en silencio,
  ruta relativa documental, y exportación a Excel (4 hojas).

**Incidente durante la verificación manual (autocorregido)**: al probar la
interfaz en vivo se registró por error una solicitud de demostración
(SOL-2026-0001) directamente en la base real, violando la regla de no
contaminarla con datos ficticios. Se detectó y se limpió por completo
(solicitud, actuaciones, documento, auditoría, vínculo con el convenio, y se
reinició el contador 2026 a 0) antes de entregar esta fase — la base real
queda con **0 solicitudes**, lista para el primer trámite real.

## 7. Errores encontrados

| Error | Estado |
|---|---|
| Contaminación accidental de la base real con una solicitud de prueba durante verificación manual | Corregido (datos eliminados, contador reiniciado) |
| Ninguno de bloqueo funcional en la lógica de negocio | — |

## 8. Decisiones técnicas relevantes

- **Sin flujo rígido**: no existe una máquina de estados obligatoria. Cada
  actuación puede cambiar estado y/o etapa opcionalmente; si no se especifica,
  se conserva el valor anterior.
- **Historial inmutable**: ninguna actuación se edita en el lugar. Una
  corrección se registra como una nueva actuación `CORRECCION` enlazada a la
  original (`id_actuacion_relacionada`), y ambas quedan visibles.
- **Eliminación siempre lógica**: `activo=0` + estado `ARCHIVADO`; no hay ruta
  de borrado físico en la interfaz.
- **Días sin movimiento y semáforo**: se calculan en vivo (no se confía en un
  valor cacheado que pueda quedar desactualizado); los umbrales del semáforo
  (`3/7/14` días) y el umbral de días hábiles para "pendiente de respuesta"
  (`5`) viven en `CONFIGURACION/config.json`, no están hardcodeados.
- **Vinculación solicitud↔convenio bidireccional** sin duplicar registros: al
  vincular, se actualiza `solicitudes.id_convenio_suscrito` y
  `convenios.id_solicitud_origen` en la misma transacción. Marcar una
  solicitud como `SUSCRITO` **nunca** crea un convenio automáticamente.

## 9. Preparación para una futura versión multiusuario

- **Capa de acceso a datos centralizada**: toda la lógica SQL de solicitudes
  vive en `services/repositorio_solicitudes.py` (patrón repositorio); las
  rutas Flask no contienen SQL. Esto es lo que permitirá, el día de la
  migración, cambiar solo esta capa (y sus pares `db_visualizador.py` /
  `db_maestra.py`) sin tocar rutas ni plantillas.
- **Configuración centralizada**: host, puerto y entorno ya no están
  hardcodeados en `app.py` — se leen de `config.json` (`aplicacion.host`,
  `aplicacion.puerto`). Los umbrales del semáforo y de pendientes de
  respuesta también son configurables.
- **`current_actor` desacoplado**: `services/current_actor.py` centraliza
  quién es "el actor actual" (hoy `USUARIO_LOCAL` fijo); la auditoría llama a
  esta función en vez de usar `getpass.getuser()` directamente, así que el
  día que exista autenticación real solo cambia esa única función.
- **Ruta relativa documental**: `documentos_tramite` guarda tanto la ruta
  absoluta como la ruta relativa al repositorio raíz (`ruta_relativa`), para
  no depender de que el documento siempre se resuelva desde este mismo
  equipo/ruta.
- **Transacciones explícitas**: generación de código, creación de solicitud,
  registro de actuación, vinculación y archivado usan `BEGIN IMMEDIATE` /
  `COMMIT` / `ROLLBACK` explícitos (no se apoyan en que "hoy solo hay un
  usuario").
- **Sin hardcodear `rsanmarti1`**: se verificó (`grep`) que ningún archivo
  `.py` contiene el nombre de usuario; la única referencia vive en
  `CONFIGURACION/config.json`, como corresponde.

## 10. Qué deberá cambiar en el despliegue multiusuario futuro

- **Motor de base de datos**: hoy el repositorio usa SQL parametrizado con
  `?` (estilo SQLite/`sqlite3`). Migrar a PostgreSQL/SQL Server requerirá
  adaptar el marcador de parámetros (`%s` o similar) y algunas funciones de
  fecha (`julianday()` es específico de SQLite) — están concentradas en
  `services/repositorio_solicitudes.py` y `services/db_visualizador.py`, no
  dispersas.
- **Concurrencia real**: `BEGIN IMMEDIATE` es la estrategia de bloqueo de
  SQLite; en un motor cliente-servidor se reemplazaría por transacciones e
  índices únicos nativos del motor (el `UNIQUE` en `codigo_solicitud` sí es
  portable).
- **Apertura de documentos**: `os.startfile()` solo funciona en el mismo
  equipo donde corre el navegador. Para acceso multiusuario real habrá que
  introducir una capa que resuelva el documento vía SharePoint/OneDrive/
  Microsoft Graph en vez de una ruta local — `services/apertura_archivos.py`
  ya aísla esta responsabilidad a un único módulo.
- **Autenticación**: reemplazar `current_actor.obtener_actor_actual()` para
  leer el usuario de una sesión autenticada real, y agregar el esquema de
  usuarios/roles/permisos mencionado en la especificación (todavía no
  implementado).
- **Despliegue**: pasar del servidor de desarrollo de Flask a un servidor
  WSGI de producción, y de `127.0.0.1` a un host accesible en red — ya
  configurable vía `config.json`, pero no desplegado.

## 11. Pendiente (explícitamente fuera de esta fase)

Integración Outlook/Microsoft Graph, envío/lectura automática de correos,
autenticación de usuarios, servidor multiusuario, migración a
PostgreSQL/SQL Server, firma electrónica.

## 12. Instrucciones de ejecución

```
python app.py
```

Abrir: **http://127.0.0.1:5000**

Para reiniciar en cualquier momento: repetir el comando desde
`SISTEMA_SEGUIMIENTO_CONVENIOS\SISTEMA`.

---

**El sistema se detiene aquí, según lo solicitado. No se implementó Outlook,
servidor multiusuario, ni migración de base de datos.**
