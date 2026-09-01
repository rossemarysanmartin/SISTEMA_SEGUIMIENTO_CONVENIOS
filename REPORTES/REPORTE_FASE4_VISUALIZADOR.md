# Reporte Fase 4 — Visualizador Web de Convenios UTMACH

Fecha: 2026-08-26

## 1. Objetivo de la fase

Construir un visualizador web local (Flask + SQLite + HTML/CSS/JS) que permita
consultar, filtrar, abrir y revisar los convenios registrados desde 2020,
usando `BASE_DATOS/convenios.db` como fuente principal (no Excel). El
repositorio documental original permanece de solo lectura en todo momento.

## 2. Correcciones aplicadas antes de esta fase (Fase 3)

Antes de construir el visualizador se detectaron y corrigieron dos errores en
el análisis documental de la Fase 3, cuyos resultados alimentan directamente
el dashboard:

- **Fecha de suscripción mal extraída**: la heurística tomaba la última fecha
  larga del documento sin filtrar, capturando en varios casos la fecha de
  fundación de la universidad ("14 de abril de 1969", presente en el membrete
  de muchos documentos) en vez de la fecha real de firma. Se corrigió para
  priorizar la fórmula de cierre legal ("a los X días del mes de...") y, en su
  defecto, exigir un año plausible (2015-2027) dentro del último tramo del
  documento.
- **Plazo de vigencia mal detectado**: la búsqueda de duración tomaba el
  primer número+unidad encontrado en la cláusula, que en muchos casos era un
  plazo de aviso previo o terminación anticipada (p.ej. "60 días") en vez de
  la vigencia total del convenio. Se corrigió para priorizar duraciones en
  años, excluir menciones cercanas a "aviso previo"/"terminación
  anticipada"/"prórroga", y admitir números escritos en palabras.
- **Falsos positivos de adenda**: el umbral de similitud (0.45) y la
  comparación sin depurar sufijos societarios ("CÍA LTDA") ni frases
  institucionales genéricas ("GOBIERNO AUTÓNOMO DESCENTRALIZADO DE...")
  producían coincidencias arbitrarias entre instituciones sin relación. Se
  corrigió elevando el umbral (0.75) y depurando esas frases antes de comparar.
- **Bug de sincronización incremental** (`db.py::insertar_matriz`): usaba
  `INSERT OR REPLACE`, que falla con `FOREIGN KEY constraint failed` al
  re-sincronizar una matriz ya existente (las hojas hijas en
  `matrices_hojas` referencian su id). Corregido a `UPDATE`-en-el-lugar,
  preservando el id y evitando el borrado conflictivo.

Con estas correcciones, sobre 866 convenios con documento relacionado
(CONFIRMADA+PROBABLE): conflictos matriz-documento bajó de 677 a 185 (21%),
posibles adendas de 757 a 223 (26%) — cifras ahora consistentes con una
revisión manual razonable, en vez de saturar al revisor con falsos positivos.

## 3. Componentes construidos

```
SISTEMA/
├── app.py                    # Aplicación Flask (factory crear_app())
├── db_context.py             # Conexión SQLite de solo lectura por-request
├── routes/
│   ├── dashboard.py          # Panel principal
│   ├── convenios.py          # Lista, ficha, próximos/vencidos/revisión, apertura de archivos
│   └── sincronizacion.py     # Historial, ejecutar sincronización, exportar Excel
├── services/
│   ├── db_visualizador.py    # Todas las consultas SQL de lectura
│   ├── apertura_archivos.py  # Apertura segura (valida ruta autorizada)
│   └── sincronizacion.py     # Orquesta el pipeline incremental en hilo de fondo
├── templates/                # dashboard, convenios_lista, convenio_ficha,
│                              # proximos_vencer, vencidos, revision_pendiente,
│                              # sincronizacion, error_apertura, base
├── static/css/estilo.css     # Estilo institucional sobrio, responsive
├── tests/test_visualizador.py
└── README.md
```

## 4. Rutas disponibles

| Ruta | Descripción |
|---|---|
| `/` | Dashboard con tarjetas y próximos a vencer |
| `/convenios` | Buscador + filtros + tabla paginada/ordenable |
| `/convenios/<id>` | Ficha individual completa |
| `/proximos-a-vencer` | Vista especializada |
| `/vencidos` | Vista especializada con filtros |
| `/revision-pendiente` | Registros incompletos/con incidencias |
| `/sincronizacion` | Historial + botón de sincronización |
| `/sincronizacion/ejecutar` (POST) | Dispara el pipeline incremental |
| `/sincronizacion/estado` | Estado JSON (para polling) |
| `/exportar-excel` (POST) | Regenera el Excel maestro desde SQLite |
| `/abrir-documento`, `/abrir-carpeta` | Apertura segura (solo rutas autorizadas) |

## 5. Número de convenios visibles (tras la sincronización más reciente)

- Total (clasificación CONVENIO): **910**
- 🟢 Vigentes: 465 · 🟡 Próximos a vencer: 37 · 🔴 Vencidos: 387 · ⚪ Sin información: 21
- 🟠 Requieren revisión: 239 · 🔵 Posible adenda: 223

## 6. Filtros implementados

Año, tipo de convenio, estado de vigencia, administrador, institución (texto
libre), tiene adenda, requiere revisión — combinables entre sí y con el
buscador global (institución, código, número, tipo, administrador, objeto,
año; tolerante a mayúsculas/tildes y coincidencias parciales).

## 7. Pruebas realizadas

- **Automatizadas** (`pytest tests/ -v`): **29/29 pasaron** — cálculo de
  vigencia (vigente/próximo/vencido/sin información), cálculo de fecha de
  finalización por duración, apertura segura de rutas (acepta autorizadas,
  rechaza ajenas), búsqueda (case-insensitive), filtros combinados,
  paginación, consistencia de contadores del dashboard, fichas individuales
  para los 8 escenarios de dominio pedidos (vigente, vencido, próximo a
  vencer, sin fecha, con posible adenda, coincidencia probable, PDF
  escaneado, firma electrónica detectada), 404 en convenio inexistente, y
  las 6 rutas principales.
- **Manuales end-to-end** contra el servidor real:
  - Dashboard carga y sus tarjetas coinciden con SQLite.
  - Búsqueda y filtros combinados (`/convenios?q=universidad&anio=2021`) — OK.
  - 5+ fichas individuales abiertas (incluyendo un caso con conflicto real:
    HIAS 2021-COOP-03, que muestra correctamente la alerta ⚠️ sin sobrescribir
    la fecha de la matriz).
  - **Abrir documento** y **Abrir carpeta** con una ruta real del repositorio
    — ambas abrieron el archivo/carpeta correctamente (HTTP 302 → 200, sin
    excepciones en el servidor).
  - **Apertura rechazada** para una ruta fuera del repositorio
    (`C:\Windows\System32\cmd.exe`) — HTTP 400, como se exige.
  - **Sincronización incremental** ejecutada dos veces de punta a punta desde
    el botón 🔄 (inventario → base maestra → análisis documental), la segunda
    corrida confirmando que el bug de `INSERT OR REPLACE` quedó resuelto.
    Resultado registrado en el historial con duración y detalle.
  - **Exportar Excel** ejecutado desde el botón 📊 — el archivo
    `BASE_MAESTRA_CONVENIOS_2020_2026.xlsx` se regeneró correctamente desde
    SQLite.

## 8. Errores encontrados (y su estado)

| Error | Origen | Estado |
|---|---|---|
| Fecha de suscripción capturaba texto de membrete/antecedentes | Fase 3 (`extractor_clausulas.py`) | Corregido |
| Plazo de vigencia capturaba avisos previos, no la duración total | Fase 3 (`extractor_clausulas.py`) | Corregido |
| Falsos positivos masivos de adenda por sufijos/frases genéricas | Fase 3 (`adendas.py`) | Corregido |
| `FOREIGN KEY constraint failed` al re-sincronizar una matriz | Fase 0/1 (`db.py`), solo se manifiesta al re-ejecutar | Corregido |
| `UnicodeDecodeError` en el hilo lector de un subproceso (acentos) | Fase 4 (`services/sincronizacion.py`) | Corregido (encoding UTF-8 explícito) |
| 3 documentos requieren OCR y Tesseract no pudo instalarse en este entorno (bloqueos de red) | Fase 0/1/3 | Sin resolver — marcados `OCR_NO_DISPONIBLE`, requieren revisión manual; no afectan al resto del sistema |

## 9. Pendiente (explícitamente fuera de esta fase)

Módulo de solicitudes, trazabilidad de solicitudes, integración Outlook/
Microsoft Graph, autenticación de usuarios, carga de archivos, validación
jurídica de firmas electrónicas.

## 10. Instrucciones de ejecución

Desde `SISTEMA_SEGUIMIENTO_CONVENIOS\SISTEMA`:

```
python app.py
```

Abrir en el navegador: **http://127.0.0.1:5000**

Para detener: `Ctrl+C`. Para reiniciar en cualquier momento: repetir
`python app.py` desde esa misma carpeta (no requiere pasos adicionales). Si
el comando `python` no resuelve al intérprete correcto, usar la ruta
completa: `C:\Users\rsanmarti1\AppData\Local\Programs\Python\Python312\python.exe`.

---

**El sistema se detiene aquí, según lo solicitado. No se ha construido el
módulo de solicitudes ni de trazabilidad.**
