# Fase 6.5 — Dashboard Ejecutivo Portable

Fecha de generación de este reporte: 26/08/2026

## 1. Objetivo de la fase

Crear una **versión ejecutiva de consulta**, independiente de Python, Flask y
SQLite, que pueda enviarse por correo o copiarse a otra computadora y abrirse
con doble clic para que la Dirección/Jefatura revise el estado de convenios y
solicitudes sin instalar nada. Esta fase es **aditiva**: no modifica la
aplicación Flask existente, no toca el repositorio documental original y no
escribe en `convenios.db`.

## 2. Archivo generado

| Dato | Valor |
|---|---|
| Ruta | `SISTEMA_SEGUIMIENTO_CONVENIOS\DASHBOARD_EJECUTIVO\DASHBOARD_CONVENIOS_UTMACH.html` |
| Tamaño | 852.4 KB (un solo archivo, sin dependencias externas) |
| Fecha de corte incorporada | 26/08/2026 14:22 |
| Convenios incluidos | 910 |
| Solicitudes incluidas | 0 (no existen solicitudes reales registradas todavía) |

El archivo es 100% autocontenido: CSS y JavaScript están incrustados en el
propio HTML, los datos son un bloque JSON embebido (`const DATOS = {...}`), y
no existe ninguna llamada a `http://`, `https://`, CDN ni recurso externo
(verificado automáticamente, ver sección 5).

## 3. Cómo generarlo de nuevo

Desde `SISTEMA_SEGUIMIENTO_CONVENIOS\SISTEMA`:

```
python generar_dashboard_ejecutivo.py
python generar_dashboard_ejecutivo.py --historico
```

`--historico` además guarda una copia con fecha en
`DASHBOARD_EJECUTIVO\HISTORICO\DASHBOARD_CONVENIOS_UTMACH_AAAA-MM-DD.html`.

También puede generarse sin usar la terminal, desde la propia aplicación:
**⚙️ Configuración → Dashboard ejecutivo portable → Generar dashboard
ejecutivo** (con la misma opción de copia histórica como casilla).

Cada generación es una **fotografía**: no se actualiza sola cuando cambian
los datos en `convenios.db`. Hay que repetir el paso anterior cuando se
quiera una versión más reciente.

## 4. Qué contiene el dashboard

- **Resumen**: tarjetas de convenios (total, vigentes, próximos a vencer,
  vencidos, sin información, revisión pendiente) y de solicitudes (total, en
  gestión, pendientes de respuesta, en jurídico, en factibilidad, en firma,
  sin movimiento, suscritas), más tres gráficos de barra simples (por año,
  por tipo, por estado de vigencia) implementados sin librerías externas.
- **Convenios**: tabla con Año/Código/Institución/Tipo/Fecha de
  suscripción/Fecha de terminación/Estado/Administrador, con búsqueda local
  (institución, código, tipo, administrador) y filtros por año/tipo/estado de
  vigencia con botón "Limpiar filtros". Cada fila abre una ficha con objeto,
  fechas y una nota de "Documento disponible en repositorio institucional" o
  "Expediente documental no localizado" — nunca una ruta de archivo.
- **Próximos a vencer** y **Vencidos**: vistas dedicadas, la de vencidos
  marcando "Vigencia pendiente de validar por posible adenda" cuando
  corresponde, para no dar una conclusión de vencimiento engañosa.
- **Revisión pendiente**: descripciones administrativas simples (Falta
  información de vigencia / Relación documental por revisar / Documento no
  localizado / Posible adenda / Conflicto entre matriz y documento) en lugar
  de nombres técnicos de columnas.
- **Solicitudes**: tabla de solo consulta (código, institución, fecha de
  ingreso, medio, responsable, pendiente actual, estado, días sin
  movimiento) con búsqueda y filtro por estado; al no existir solicitudes
  reales hoy, se muestra el mensaje "Actualmente no existen solicitudes
  registradas." — nunca datos ficticios. Cuando existan, cada fila abrirá su
  trazabilidad (fecha, actuación, dependencia, responsable, resultado) de
  solo lectura.
- Leyenda visible en el pie: "Dashboard ejecutivo de consulta — no permite
  modificar información" y remisión al sistema completo para gestión.

## 5. Privacidad y pruebas automáticas

Antes de escribir el archivo, el generador ejecuta siempre
`verificar_sin_datos_sensibles()`, que bloquea la escritura si detecta
patrones como rutas `C:\Users\...`, `SECRET_KEY`, `password`, `traceback` o
errores de `sqlite3`. Además, ninguna ruta absoluta de documento se incorpora
nunca al HTML (solo un indicador booleano de disponibilidad).

Se agregaron **14 pruebas nuevas** en `tests/test_dashboard_ejecutivo.py`,
todas contra una base SQLite temporal (nunca la real):

- fecha de corte presente en los datos;
- exportación real de convenios (conteos correctos, incluidos vencidos);
- indicador de expediente disponible sin exponer la ruta;
- marcado de revisión por posible adenda;
- estado vacío correcto cuando no hay solicitudes reales;
- solicitud real con pendiente actual y trazabilidad calculados correctamente;
- el verificador de privacidad detecta rutas absolutas de Windows y
  `SECRET_KEY`;
- la exportación real nunca incluye la ruta absoluta de un documento;
- el HTML generado pasa la verificación de privacidad;
- ausencia de CDN externos y de cualquier `http://`/`https://`;
- escritura del archivo (y copia histórica) dentro de un directorio temporal
  aislado;
- bloqueo explícito de escritura fuera de `SISTEMA_SEGUIMIENTO_CONVENIOS`
  (reutilizando el guard `seguridad.verificar_ruta_escritura_segura`);
- agrupación correcta del gráfico por año.

**Resultado de la suite completa: 81/81 pruebas aprobadas** (67 de las fases
anteriores, sin cambios, + 14 nuevas).

## 6. Qué NO se hizo (fuera de alcance de esta fase)

- No se modificó la aplicación Flask existente más allá de un botón
  administrativo aditivo en Configuración.
- No se tocó `convenios.db` ni el repositorio documental original.
- No se incrustaron documentos, imágenes pesadas ni la base SQLite.
- No se implementó actualización en tiempo real: es deliberadamente una
  fotografía, hasta el futuro despliegue multiusuario en servidor
  institucional.

## 7. Limitaciones de la versión portable

- Los datos quedan congelados en el momento de la generación; para
  actualizarlos hay que volver a ejecutar el generador.
- Los documentos no son accesibles desde el HTML portable (rutas locales no
  tienen sentido en otra computadora); solo se indica si existe expediente
  localizado.
- Los gráficos son barras simples locales, no una herramienta de BI.
- Pensado para revisión ejecutiva, no reemplaza al sistema completo para
  gestión y actualización de datos.
