# Inventario unificado Collector / Business

## Tabla y compatibilidad

Se amplía la tabla real del repositorio, **`wine_inventory_items`** (no se crea otra tabla paralela `wine_items`). Ambas modalidades usan la misma entidad y los mismos endpoints. El propósito del espacio no obliga a rellenar ni a borrar campos específicos de la otra modalidad.

La columna física `wine_name` se renombra a **`name`** conservando sus datos. La API acepta tanto `name` como el alias legacy `wine_name` y devuelve ambos con el mismo valor. Si se envían ambos con valores distintos, devuelve `422`. Los clientes existentes pueden seguir enviando `wine_name`, `wine_type`, `age_years` y `quantity`.

`wine_cellar_id` siempre se toma de la ruta; no se puede mover un ítem a otra cava enviando ese campo en el cuerpo. La autorización sigue resolviendo la membresía y el rol a partir de la cava y su espacio.

## Campos

Al crear, **solo `name` es obligatorio**; `quantity` vale `0` si se omite. Los demás datos de ficha son opcionales y se almacenan como SQL `NULL` si faltan. Los textos opcionales vacíos se normalizan a `null`, no a valores ficticios.

| Grupo | Campos / formato |
|---|---|
| Núcleo | `id` UUID y `wine_cellar_id` UUID generados/asignados por backend; `name` texto no vacío hasta 255; `winery` hasta 255; `vintage` año de cuatro dígitos o `NV`; `quantity` entero >= 0; `physical_location` hasta 255 |
| Ficha | `country` hasta 100; `region`, `appellation`, `wine_type`, `aging`, `consumption_window` hasta 255; `bottle_format` hasta 50; `alcohol_percentage` decimal 0–100 |
| Costos/control | `purchase_price`, `sale_price`: decimal no negativo, hasta dos decimales; `min_stock_alert`: entero >= 0; `supplier_name` hasta 255; `origin_type`; `purchase_date` fecha ISO `YYYY-MM-DD`; `batch_invoice_number` hasta 100 |
| Cata simplificada | `tasting_notes`, `company_notes` (notas internas): hasta 4000 caracteres; `would_buy_again`: boolean; todos opcionales y nullable |
| Experiencia legacy | `rating`: **escala de 1–100 puntos**; `body_slider`, `acidity_slider`, `tannins_slider`: **0–5**; `aroma_tags`: array de hasta 50 textos de 1–64 caracteres; `occasion_notes`: hasta 4000 caracteres; todos opcionales y nullable |
| Compatibilidad | `wine_name`: alias de `name`; `age_years`: entero >= 0 opcional, sin convertirlo automáticamente a añada |

- `vintage` admite números como `2020` en entrada y devuelve la cadena `"2020"`; `nv` se normaliza a `"NV"`. No se calcula la añada a partir de la edad ni viceversa.
- `origin_type` devuelve `STORE`, `GIFT`, `TRIP` o `SUPPLIER`. Acepta también Tienda, Regalo, Viaje y Proveedor, sin distinguir mayúsculas/minúsculas.
- Los decimales se serializan como **strings con dos decimales** para preservar precisión: `"19.99"`, `"94.00"`, `"4.50"`. Los precios usan `NUMERIC(12,2)`; no se realiza conversión de moneda.
- La escala de rating es única: un valor `5` significa 5/100, no cinco estrellas. Si la UI usa estrellas, debe convertirlas explícitamente antes de enviar.
- `null`, `false`, `0` y `[]` son distintos. Por ejemplo, `would_buy_again: null` significa sin valoración y `false` significa que no volvería a comprarlo. `aroma_tags: null` se guarda como SQL NULL; `[]` representa una lista explícitamente vacía.
- No se generan alertas nuevas con `min_stock_alert` en este cambio: queda persistido para su posterior evaluación.
- La cata simplificada no requiere métricas técnicas: pueden omitirse o enviarse como `null`. Los valores legacy se conservan si se omiten al actualizar. `tasting_notes` es independiente de `occasion_notes` y `company_notes`; los textos vacíos se convierten a `null` y `would_buy_again: false` se conserva.

## Crear y actualizar

```http
POST /api/v1/wine-cellars/{wine_cellar_id}/inventory
Authorization: Bearer <access-token>
Content-Type: application/json

{"name":"Reserva personal","vintage":"NV","quantity":3,"origin_type":"GIFT"}
```

El mismo endpoint admite datos Business:

```json
{
  "name":"Reserva de la casa",
  "winery":"Bodega Ejemplo",
  "vintage":2020,
  "quantity":24,
  "physical_location":"Estante A2",
  "purchase_price":"12.50",
  "sale_price":"28.00",
  "min_stock_alert":6,
  "supplier_name":"Distribuidor",
  "batch_invoice_number":"FAC-001"
}
```

Creación devuelve `201` con la entidad completa y los campos sin completar a `null`. El listado existente devuelve el mismo DTO ampliado. Se validan las cuotas agregadas del espacio: FREE Collector hasta 50 botellas, FREE Business hasta 25 registros/SKUs; PRO sin cuota de inventario. Altas, PUT/PATCH e importaciones no pueden eludirlas y devuelven `403`/`ITEM_LIMIT_REACHED` si aumentan el consumo por encima del máximo. Detalles y metadatos frontend: [resource-quotas.md](resource-quotas.md).

Actualizaciones:

```http
PATCH /api/v1/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}

{"supplier_name":null,"purchase_price":"13.00"}
```

`PATCH` y el `PUT` existente usan actualización parcial compatible:

- Un campo **omitido conserva** su valor, incluidos los campos avanzados desconocidos por clientes antiguos.
- Un campo opcional enviado como **`null` se limpia**.
- No se admite `name: null`, nombre vacío ni `quantity: null`.
- Enviar `quantity` establece un conteo absoluto. Para registrar una salida con motivo e historial, usar el endpoint de movimientos, no restar stock localmente y después enviar un PUT.

## Salidas / descorche transaccional

```http
POST /api/v1/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}/movements
Authorization: Bearer <access-token>
Content-Type: application/json

{"quantity":1,"reason":"uncorking","notes":"Cena con amigos"}
```

Motivos: `sale`, `tasting`, `breakage`, `uncorking`. Se aceptan para ambos propósitos; no se obliga a Collector a gestionar precios de venta ni a Business a rellenar notas de cata. `quantity` es un entero estricto mayor que cero; `notes` es opcional y admite hasta 4000 caracteres.

El backend bloquea el ítem (`SELECT FOR UPDATE`), comprueba stock suficiente y guarda **el descuento y el movimiento en una sola transacción**. Las actualizaciones normales también bloquean la fila para no sobrescribir una salida concurrente con un stock leído previamente.

Respuesta `201`:

```json
{
  "id":"<uuid-movimiento>",
  "inventory_item_id":"<uuid-item>",
  "user_id":123,
  "reason":"uncorking",
  "quantity":1,
  "stock_before":3,
  "stock_after":2,
  "notes":"Cena con amigos",
  "created_at":"2026-11-16T12:00:00"
}
```

El autor y la fecha provienen del backend, no del cuerpo enviado. El frontend puede actualizar el stock visible con `stock_after`. Un ítem con stock cero **no se elimina automáticamente**.

- Stock insuficiente: `409`, sin descuento ni movimiento parcial.
- Ítem inexistente o de otra cava: `404`; espacio ajeno o rol insuficiente: `403`; datos inválidos: `422`.
- Si falla el historial después de actualizar el stock, se revierte toda la transacción.
- No hay idempotencia automática por solicitud: cada POST exitoso es una salida nueva. Deshabilitar el botón durante el envío y no reintentar automáticamente una operación cuyo resultado se desconoce.

Historial acotado, ordenado del más reciente al más antiguo:

```http
GET /api/v1/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}/movements?limit=100
```

`limit` admite 1–500. OWNER, SOMMELIER e INVENTORY_CLERK pueden registrar salidas; WAITER tiene lectura, como en el resto del inventario. Las notas de descorche pertenecen al movimiento; no sobrescriben las notas maestras del vino.

El historial es operativo, no un libro fiscal inmutable: se elimina en cascada si se borra el ítem, su cava o su espacio. La confirmación destructiva del frontend debe incluir este efecto. El PUT absoluto y la importación de conteos no generan movimientos de salida ficticios.

## Excel e IA

El Excel legacy y la plantilla conservan su formato básico (`wine_name`, `wine_type`, `age_years`, `quantity`). Admiten celdas vacías en tipo/edad y conservan los metadatos avanzados de los IDs que actualizan. Los informes nuevos de espacio/cava en Excel y PDF, con ficha ampliada y hoja de importación separada por cava, usan `GET /api/v1/inventory/export`; contrato: [inventory-exports.md](inventory-exports.md).

La proyección de IA acepta tipo/edad desconocidos y añade añada si existe. Sigue enviando únicamente campos mínimos y resúmenes acotados; no envía costos, notas personales, compañía ni aromas a Gemini por incorporar estas columnas al modelo maestro.

## Migración y pruebas

La revisión `20261118_simplified_tasting`, posterior a `20261117_resource_quotas`, agrega `tasting_notes` nullable y asegura que las métricas técnicas y los campos de cata simplificada admitan SQL `NULL`, sin borrar valores existentes. Aplicarla antes de iniciar la API actualizada.

La revisión `20261116_unified_wine_items` sigue a `20261116_space_memberships`. Conserva IDs, relaciones, nombres y stock existentes; agrega columnas nullable, restricciones e historial de salidas. No se ha ejecutado sobre la base habitual durante el desarrollo.

Con respaldo y API detenida, revisar el destino de `.env` y ejecutar:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

Si datos antiguos incumplen las restricciones, la migración aborta; no se corrigen ni borran silenciosamente. El downgrade destructivo está bloqueado porque perdería ficha e historial. El arranque exige el esquema actualizado; no usar `create_all` o `stamp head` como sustitutos de migrar.

Pruebas sobre esquemas PostgreSQL temporales, sin consumir cuota de IA:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_unified_wine_items.py -v
```
