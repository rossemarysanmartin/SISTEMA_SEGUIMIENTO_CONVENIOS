# Visualizador Web de Convenios — UTMACH

Aplicación web local (Flask) para consultar, filtrar y revisar los convenios
interinstitucionales de UTMACH registrados en `BASE_DATOS/convenios.db`.

**El repositorio documental original (`CONVENIOS INTERINSTITUCIONALES UTMACH`)
es de SOLO LECTURA.** Esta aplicación nunca escribe, mueve, renombra ni borra
nada dentro de él; todo lo que genera vive dentro de `SISTEMA_SEGUIMIENTO_CONVENIOS`.

## Requisitos

- Python 3.12 (ya instalado en este equipo en
  `C:\Users\rsanmarti1\AppData\Local\Programs\Python\Python312\python.exe`)
- Las dependencias listadas en `requirements.txt`

## Instalación

Desde la carpeta `SISTEMA_SEGUIMIENTO_CONVENIOS\SISTEMA`:

```
python -m pip install -r requirements.txt
```

> Nota: si el comando `python` no resuelve al intérprete correcto (puede
> aparecer el acceso directo de Microsoft Store), use la ruta completa:
> `C:\Users\rsanmarti1\AppData\Local\Programs\Python\Python312\python.exe`

## Ejecución

Desde la carpeta `SISTEMA_SEGUIMIENTO_CONVENIOS\SISTEMA`:

```
python app.py
```

Luego abrir en el navegador:

```
http://127.0.0.1:5000
```

Para detener la aplicación: `Ctrl+C` en la terminal donde se ejecuta.

Para volver a iniciarla en cualquier momento, repetir `python app.py` desde
esa misma carpeta — no requiere ningún paso adicional de configuración.

## Estructura del proyecto

```
SISTEMA/
├── app.py                 # Punto de entrada Flask
├── db_context.py          # Conexión SQLite de solo lectura por-request
├── config.py               # Carga CONFIGURACION/config.json y rutas derivadas
├── routes/                 # Blueprints (dashboard, convenios, sincronizacion)
├── services/               # Acceso a datos, apertura segura de archivos, sincronización
├── templates/               # Vistas Jinja2
├── static/css/              # Estilos
├── tests/                   # Pruebas automatizadas (pytest)
└── (módulos de fases anteriores: inventario.py, construir_base_maestra.py,
    analizar_documentos_principales.py, extractor_clausulas.py, etc.)
```

## Funcionalidades

- **Dashboard**: tarjetas con totales de convenios por estado de vigencia,
  revisión pendiente y posible adenda (todo calculado en vivo desde SQLite).
- **Convenios**: buscador global + filtros combinables + tabla paginada y
  ordenable.
- **Ficha individual**: información general, documental, control de calidad,
  documentos del expediente, evidencias documentales (con página y fragmento
  fuente) y alertas de conflicto/adenda.
- **Próximos a vencer / Vencidos / Revisión pendiente**: vistas especializadas.
- **Sincronización**: botón que ejecuta el pipeline incremental completo
  (inventario → base maestra → análisis documental) y guarda el historial.
- **Exportar Excel**: regenera `BASE_MAESTRA_CONVENIOS_2020_2026.xlsx` desde
  SQLite (SQLite sigue siendo la fuente de verdad).
- **Apertura segura de archivos**: "Abrir documento" / "Abrir carpeta" solo
  funcionan para rutas dentro del repositorio autorizado; cualquier otra ruta
  es rechazada (HTTP 400).

## Pruebas

```
python -m pip install pytest
python -m pytest tests/ -v
```

## Módulo de Solicitudes y Trazabilidad (Fase 5)

Accesible desde el menú **📩 Solicitudes**. Permite registrar trámites de
convenio desde su ingreso (correo, oficio, sistema institucional, etc.) hasta
su suscripción, con una línea de tiempo de actuaciones (traslados,
delegaciones, solicitudes de criterio/informe, respuestas), semáforo de
días sin movimiento configurable, pendientes de respuesta, tablero por
etapas, y vinculación con el inventario de convenios ya suscritos. Ver
`REPORTES\REPORTE_FASE5_SOLICITUDES_TRAZABILIDAD.md` para el detalle
completo.

## Estabilización y usabilidad (Fase 6)

Acciones rápidas (Delegar, Solicitar criterio, Registrar respuesta, etc.),
"Pendiente actual" calculado, catálogos administrables sin borrado físico
(**⚙️ Configuración → Catálogos**), semáforo editable desde la interfaz
(**⚙️ Configuración → Semáforo**), búsqueda global en la cabecera, panel
**🗓 Mi trabajo**, notas internas, edición auditada y archivar/reactivar. Ver
`REPORTES\REPORTE_FASE6_ESTABILIZACION.md` para el detalle completo.

## Dashboard Ejecutivo Portable (Fase 6.5)

Genera un único archivo HTML autocontenido (sin Python, Flask ni SQLite) con
una fotografía de los datos actuales, pensado para enviar por correo o abrir
con doble clic en cualquier computadora:

```
python generar_dashboard_ejecutivo.py
python generar_dashboard_ejecutivo.py --historico   # además guarda copia con fecha
```

También puede generarse desde **⚙️ Configuración → Dashboard ejecutivo
portable**. El archivo se crea en `DASHBOARD_EJECUTIVO\DASHBOARD_CONVENIOS_UTMACH.html`
y nunca contiene rutas locales, credenciales ni información técnica interna.
Ver `REPORTES\REPORTE_FASE6_5_DASHBOARD_EJECUTIVO.md` para el detalle
completo.

## Pendiente (fases futuras, NO incluidas aquí)

Integración con Outlook / Microsoft Graph, autenticación de usuarios,
servidor multiusuario, migración de SQLite a PostgreSQL/SQL Server,
validación jurídica de firmas.
