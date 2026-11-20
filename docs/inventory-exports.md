# Descarga de inventario: Excel y PDF

## Endpoint de informes

```http
GET /api/v1/inventory/export?space_id=<uuid>&format=xlsx
GET /api/v1/inventory/export?space_id=<uuid>&cellar_id=<uuid>&format=pdf
Authorization: Bearer <access-token>
```

- `space_id` UUID **obligatorio**; `cellar_id` UUID opcional. Sin cava, incluye todos los ítems de todas las cavas del espacio; con cava, solo sus ítems. No depende de una selección global del servidor.
- `format=xlsx|pdf`; por defecto `xlsx`. Un formato no soportado, UUID inválido o espacio omitido devuelve `422`.
- Exige usuario activo y membresía con permiso READ del espacio indicado (todos los roles existentes, incluido WAITER). No hay bypass por owner legacy ni superuser. Token inválido/ausente/refresh o usuario inactivo: `401`; espacio ajeno: `403`; espacio inexistente o cava ausente/ajena al espacio: `404`.
- Valida siempre la pareja espacio/cava, incluso si el usuario tiene acceso a ambos espacios. La consulta SQL filtra por espacio y cava antes de generar el documento. No hay llamadas a IA ni escrituras en inventario.
- Límite síncrono de 10000 registros; si se supera, responde `413` sin generar un informe parcial. Filtrar por cava si es posible. No es una paginación ni un truncado silencioso del inventario.
- Incluye registros con cantidad cero. El informe refleja la lectura de los ítems al consultar, no bloquea movimientos concurrentes ni garantiza que los valores sigan iguales tras la descarga.

## Respuesta y frontend

- Excel: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- PDF: `application/pdf`.
- Ambos: `Content-Disposition: attachment; filename="vinevault-<espacio>-<cava-o-todas>-<id>-<fecha>.<ext>"`. Nombre ASCII seguro, sin caracteres de control ni saltos de línea; fecha UTC.
- `Content-Disposition` está expuesto por CORS para que Angular pueda leerlo. Usar `responseType: 'blob'` y `observe: 'response'`; incluir el Bearer token, crear un object URL, descargar y revocarlo después. Cambiar el formato modifica solo el parámetro `format`.
- `Cache-Control: private, no-store` y `X-Content-Type-Options: nosniff`; los archivos contienen datos y notas del usuario.
- Errores de generación: `500` con mensaje genérico, sin trazas ni contenido del archivo en la respuesta. No intentar abrir un cuerpo de error JSON como si fuera un PDF/Excel.

## Excel legible y compatibilidad de importación

La hoja **`Inventario`** es un informe: cabecera con espacio/cava, propósito, fecha UTC y totales; encabezados en fila 8, filtros, paneles congelados y anchos/ajustes de texto. Contiene nombre, bodega, añada, cantidad, ubicación, país/región/apelación, tipo/cepa, formato, crianza, alcohol, ventana y notas relevantes.

- COLLECTOR: precio pagado, origen y fecha de compra.
- BUSINESS: coste unitario, precio de venta, stock mínimo, proveedor y lote/factura.
- Precios son números con dos decimales; fechas de compra son fechas Excel. No se inventa moneda ni se convierten valores. Los textos del usuario se escriben como strings, nunca fórmulas; controles incompatibles con XML se eliminan.
- Si se seleccionó una cava, añade la hoja **`inventory`** con los encabezados históricos `id`, `wine_name`, `wine_type`, `age_years`, `quantity` en la primera fila. Esta hoja permite reimportar **en la misma cava** mediante el endpoint existente. El importador selecciona esa hoja, no la hoja visual.
- Editar la hoja visual no actualiza la hoja de importación. El importador sigue modificando solo los campos básicos; conserva metadatos avanzados existentes por ID, no permite mover IDs entre cavas y no restaura notas/precios desde este informe.
- Un informe de todo el espacio **no incluye** la hoja `inventory`: no debe importarse en una única cava mezclando registros de otras. El importador lo rechaza con `422`, antes de modificar datos. Para altas, usar la plantilla de la cava destino.
- Inventario vacío: cabecera, mensaje de ámbito vacío y, si hay cava seleccionada, hoja `inventory` con solo encabezados (reimportación sin cambios).

## PDF ejecutivo

A4 horizontal con espacio, cava/ámbito, propósito, fecha UTC, número de registros y unidades. Tabla resumida con cava, vino, bodega, añada, cantidad, tipo/cepa, compra o coste/venta y ventana registrada. No incluye el texto completo de notas; para ese detalle usar Excel.

Repite encabezados de tabla y numera páginas; ajusta nombres largos con salto de línea. Incluye una fuente distribuida con ReportLab para acentos españoles sin depender de las fuentes del sistema. Los textos se escapan antes de componer el documento; no ejecuta HTML ni descarga imágenes/recursos de datos del usuario. Un ámbito vacío genera un PDF válido de una página, no un archivo vacío.

## Rutas existentes, sin cambios de contrato

```http
GET  /api/v1/wine-cellars/{wine_cellar_id}/inventory/template
GET  /api/v1/wine-cellars/{wine_cellar_id}/inventory/export
POST /api/v1/wine-cellars/{wine_cellar_id}/inventory/import
```

Todas conservan autenticación y autorización por la cava de la ruta. La plantilla sigue siendo `.xlsx`, con los mismos encabezados y filas de ejemplo. El export legacy sigue generando el Excel básico de una cava. La importación sigue recibiendo multipart `file`, no PDF; conserva validaciones, cuotas y transacción. No exige `space_id` adicional en estas rutas legacy porque el espacio se resuelve desde la cava, para no romper clientes existentes.

El lector XLSX admite relaciones de hoja relativas y absolutas (`/xl/worksheets/...`) como las generadas por openpyxl. No se interpreta la cabecera del informe como encabezado de importación.

## Dependencias y verificación

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_inventory_exports.py -v
```

Requiere openpyxl y ReportLab, declarados en `requirements.txt`; generación síncrona delegada al threadpool de la aplicación, sin ficheros temporales ni migraciones. Para incluir API/aislamiento SQL, definir `TEST_DATABASE_URL` explícito: los tests usan esquemas temporales y no ejecutan seeds. Se comprueba contenido/estructura XLSX/PDF, paginación, aislamiento, pareja espacio/cava, plantilla y reimportación compatible sin borrar datos avanzados.
