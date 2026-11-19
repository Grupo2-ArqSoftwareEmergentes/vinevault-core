# Asistente conversacional de inventario

## Endpoint y autorización

`POST /api/v1/assistant/chat`, `Content-Type: application/json`, `Authorization: Bearer <access-token>`.

```json
{
  "space_id": "<uuid-del-espacio>",
  "cellar_id": null,
  "mode": "CHAT",
  "message": "¿Qué vinos tengo disponibles para acompañar una parrilla?",
  "history": [
    {"role": "user", "content": "Busco un tinto de mi inventario."},
    {"role": "assistant", "content": "¿Qué comida vas a preparar?"}
  ]
}
```

- `space_id` UUID obligatorio; `cellar_id` UUID opcional limita el análisis a esa cava. No acepta `wine_cellar_id` como alias.
- `mode`: `CHAT` por defecto o `SOMMELIER_ANALYSIS`.
- `message`: texto recortado de 1–2000 caracteres. Obligatorio también en análisis; puede indicar el enfoque deseado.
- `history`: omitido, `null` o lista de hasta 10 mensajes, cada uno con `role: user|assistant` y `content` de 1–2000 caracteres. Roles `system`/`tool`, campos extra e historiales mayores se rechazan con `422`, no se truncan silenciosamente.
- Requiere usuario activo y membresía del **espacio solicitado**, con permiso `ANALYZE`: OWNER, SOMMELIER o INVENTORY_CLERK, en ambos modos. WAITER, superuser sin membresía y owner legacy sin membresía no tienen acceso. Sin sesión válida: `401`; sin permiso: `403`, incluso si el espacio no existe (no se revela su existencia). Una cava ajena a ese espacio o ausente devuelve `404` después de autorizar el espacio, aunque el usuario también pertenezca al otro espacio.
- La dependencia `app/assistant/interfaces/rest/security.py` protege el cuerpo tipado antes de consultar inventario o llamar a DeepSeek; no utiliza el guard genérico de rutas con IDs indirectos.

## Respuesta

```json
{
  "reply": "Dispones de tres botellas del vino registrado…",
  "mode": "CHAT",
  "context_summary": {
    "space": {"id": "<uuid>", "name": "Casa", "purpose": "COLLECTOR"},
    "cellar": null,
    "space_totals": {
      "items": 1,
      "bottles": 3,
      "cellars": 1,
      "purchase_value_known": "30.00",
      "items_missing_purchase_price": 0,
      "sale_value_known": null,
      "items_missing_sale_price": null
    },
    "scope_totals": {
      "items": 1,
      "bottles": 3,
      "cellars": 1,
      "purchase_value_known": "30.00",
      "items_missing_purchase_price": 0,
      "sale_value_known": null,
      "items_missing_sale_price": null
    },
    "items_considered": 1,
    "truncated": false
  }
}
```

- `space_totals` agrega todas las cavas del espacio autorizado; `scope_totals` solo la seleccionada, o todo el espacio si no se envió cava. Los totales no dependen del límite de detalle.
- `items` cuenta registros/SKUs, incluidos los de stock cero; `bottles` suma `quantity`. `cellars` incluye cavas vacías.
- Valores conocidos = suma de precio unitario registrado por cantidad. Son **parciales** cuando faltan precios. No se infiere una moneda, no son ventas realizadas, beneficios netos ni rotación. Los importes Decimal se serializan como strings. Precio de compra/coste se incluye en ambos propósitos; venta y alerta de stock solo en BUSINESS.
- `items_considered` indica cuántos registros detallados recibió el modelo. El frontend debe advertir cuando `truncated=true`: no se puede confirmar la ausencia de un vino fuera de la muestra.
- Inventario vacío en el ámbito solicitado: `200` con mensaje determinista y resumen, sin llamar a DeepSeek, aunque el resto del espacio contenga vinos. Un ítem con cantidad cero no equivale a inventario vacío.

## Contexto, límites y privacidad

- SQL proyecta solo nombre, bodega, añada, cantidad, tipo/cepa, compra/coste, ventana, notas de cata/internas relevantes y, en BUSINESS, precio de venta/alerta mínima. Cada nota se limita a 160 caracteres en SQL. No se leen dispositivos, claves, datos IAM, facturas ni movimientos para construir el prompt.
- Máximo 40 registros por consulta, primero con stock positivo y luego por nombre/ID, y máximo 12000 caracteres serializados de detalle. Se informa el recorte. No es un buscador completo de inventarios grandes: una pregunta sobre un vino fuera de la muestra puede requerir acotar a una cava o consultar el listado normal. No se inventa una respuesta usando solo los totales.
- El prompt considera el inventario actual como fuente de stock, distingue historial y datos almacenados de instrucciones y pide no inventar vinos, precios, añadas ni disponibilidad. El maridaje es orientativo. Un LLM puede equivocarse: la respuesta no sustituye los datos de inventario ni autoriza movimientos.
- A diferencia del autocompletado, el asistente **sí envía a DeepSeek una proyección del inventario y las notas indicadas**, además de la pregunta y el historial. El frontend debe comunicar esta finalidad al usuario.
- La conversación es stateless: no se guarda historial ni se modifica inventario. El cliente conserva como máximo los últimos 10 mensajes y debe reiniciarlos al cambiar de espacio/cava. El historial enviado por el cliente no se considera prueba de stock ni de acceso.
- El contexto es una lectura de varias consultas bajo el aislamiento habitual de la base; no bloquea escritores ni garantiza un snapshot transaccional frente a cambios concurrentes. No se garantiza que el stock siga igual cuando llegue la respuesta.
- No hay búsqueda web, herramientas, streaming, caché ni rate limit por cuenta en este endpoint. No depende del proveedor elegido para autocompletar ni altera la configuración de Gemini. Evitar doble envío y deshabilitar el botón durante la petición. Renderizar el texto/Markdown de forma segura, nunca como HTML confiable.

## DeepSeek y errores

Reutiliza `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` y `DEEPSEEK_REQUEST_TIMEOUT_SECONDS` de `.env`, mediante `app/shared/infrastructure/deepseek_client.py`, compartido con autocompletado. No requiere SDK/dependencias nuevas ni migraciones.

- Una llamada `/chat/completions`, sin reintentos internos ni de aplicación; thinking desactivado, máximo 800 tokens de salida. Temperatura CHAT `0.2`; SOMMELIER_ANALYSIS `0.4`.
- SOMMELIER_ANALYSIS prioriza consumo/organización/diversidad para COLLECTOR y disponibilidad/costes/precios/acciones operativas para BUSINESS; no supone demanda, movimientos ni gastos no consultados.
- Errores externos llevan `detail: {"code": "…", "message": "…"}`, sin cuerpos del proveedor ni credenciales:

| HTTP | `detail.code` | Situación |
|---|---|---|
| 429 | `quota_exceeded` | DeepSeek devuelve 402 (saldo) o 429; incluye `Retry-After: 30` orientativo, no garantiza recuperación de saldo/cuota |
| 504 | `timeout` | Timeout local/red o HTTP 408/504 del proveedor |
| 502 | `invalid_response` | JSON/contenido inválido, vacío, excesivo o generación truncada |
| 503 | `not_configured` | Clave DeepSeek ausente |
| 503 | `unavailable` | Red, autenticación del proveedor o servicio externo no disponible |

El frontend debe conservar la pregunta ante errores y permitir reintento manual; no cerrar sesión por errores externos. `401` de la propia ruta sí pertenece a la autenticación de VineVault.

## Verificación

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_assistant.py -v
```

DeepSeek siempre simulado. Para activar las pruebas de aislamiento y SQL, configurar `TEST_DATABASE_URL` explícito; usan esquemas temporales y no ejecutan seeds. Sin él, esas pruebas se omiten. La suite de `test_deepseek_autocomplete.py` verifica que la reutilización del transporte no cambie el autocompletado.
