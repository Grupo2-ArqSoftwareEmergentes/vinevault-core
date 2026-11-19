# Análisis de inventario con IA

## Autocompletar un vino por nombre (sin cata)

`POST /api/v1/inventory/ai-autocomplete`, con `Authorization: Bearer <access-token>`:

```json
{"wine_name":"Nombre del vino 2020"}
```

- `wine_name`: texto recortado, obligatorio, 1–255 caracteres. Admite además `registration_date` opcional (`YYYY-MM-DD`, desde 1900-01-01 hasta hoy UTC); si falta o es `null`, usa la fecha UTC del servidor al consultar. No acepta otros campos.
- Requiere cuenta activa y membresía en al menos un espacio existente con permiso `ANALYZE` (`OWNER`, `SOMMELIER`, `INVENTORY_CLERK`). Sin usuario válido: `401`; sin esa membresía: `403`; payload inválido: `422`. No se usa el owner legacy ni el estado superuser como autorización. No selecciona ni modifica un espacio.
- Devuelve `200 application/json` con las once claves de formulario siguientes; los datos desconocidos son `null`. La búsqueda agrega metadatos `sources`, `registration_date`, `estimated_fields`, `estimation_basis` y, solo con Gemini cuando Google lo entrega, `search_suggestions_html`, separados de los campos del vino. Si falta la clave API, falla el proveedor/búsqueda, no hay evidencia web utilizable, se agota su cuota, vence el timeout o devuelve JSON inválido, responde `200 {}`. Un nombre ambiguo debe producir sugerencias nulas, no datos inventados. La identificación es probabilística: el usuario debe confirmar los datos.

```json
{
  "winery": null,
  "vintage": null,
  "country": null,
  "region": null,
  "denomination": null,
  "grape_type": null,
  "format": null,
  "aging": null,
  "alcohol": null,
  "drinking_window_start": null,
  "drinking_window_end": null
}
```

- La consulta solicita todos los campos de Identificación/Ficha: bodega, cosecha, país, región, D.O./apelación legal, tipo/cepa, formato, crianza, alcohol y ventana. No intenta completar cantidad, ubicación física, datos comerciales/de compra ni cata. Añada es cosecha real: no se aproxima usando la fecha de compra/registro, ni se copia de otra añada del mismo vino. `NV` solo si las fuentes confirman sin añada; si no hay evidencia, `vintage: null`.
- Si las fuentes no indican una ventana para el producto/añada identificado, se permite una **estimación orientativa**, basada en el tipo/crianza documentados y la fecha de registro, asumiendo botella recién adquirida, sin abrir y bien conservada. Sin identidad/estilo suficiente no se estima. No garantiza estado ni potencial de guarda; una botella comprada hoy puede ser antigua. Los años estimados aparecen en `estimated_fields`, y `estimation_basis` explica criterio y supuestos. No se autoriza estimar otros campos. Los años explícitos de fuentes no se marcan como estimados.

Ejemplo parcial de metadatos de una ventana estimada (los años son ilustrativos, no una regla universal):

```json
{
  "registration_date": "2026-11-18",
  "drinking_window_start": 2026,
  "drinking_window_end": 2027,
  "estimated_fields": ["drinking_window_start", "drinking_window_end"],
  "estimation_basis": "Orientativa desde registro, asumiendo botella sin abrir y buena conservación; cosecha sin confirmar."
}
```

- El frontend debe mostrar «estimada» junto a la ventana cuando corresponda y permitir corregirla; mostrar también el criterio, sin tratarlo como una recomendación verificada. Sin estimación, `estimated_fields: []` y `estimation_basis: null`. Estos metadatos solo acompañan la sugerencia: no se guardan en columnas nuevas ni se envían como campos de inventario. El cuerpo antiguo con solo `wine_name` sigue siendo válido.

- Lista cerrada de salida independiente de la ficha de inventario: cualquier propiedad extra del modelo se descarta. Nunca devuelve puntuaciones, aromas, cuerpo, acidez, taninos, notas de cata/internas, argumentos de venta ni decisión de recompra.
- **Proveedor de autocompletado:** `WINE_AUTOCOMPLETE_PROVIDER=deepseek` por defecto. Selección explícita `deepseek` o `gemini`; no hay fallback automático de proveedor. El análisis de inventario mantiene Gemini y no cambia por esta selección.

```dotenv
WINE_AUTOCOMPLETE_PROVIDER=deepseek
DEEPSEEK_API_KEY=<clave-solo-backend>
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_REQUEST_TIMEOUT_SECONDS=20
```

- **DeepSeek:** una llamada `POST https://api.deepseek.com/v1/tools/search` (`count=5`, `need_content=true`), seguida de una llamada `/chat/completions` con JSON Output, thinking desactivado, temperatura `0.1` y máximo 500 tokens de salida. Usa únicamente evidencia de la búsqueda; no descarga las URLs desde Core. Contexto acotado a 5 resultados, 2000 caracteres de contenido por resultado, títulos de 300 y URLs de 2048; respuestas HTTP de hasta 512 KiB. La búsqueda acepta como máximo 128 caracteres: nombres mayores devuelven `{}` sin truncar la identidad ni llamar al proveedor. Búsqueda sin resultados/error no dispara extracción. El timeout total compartido es `DEEPSEEK_REQUEST_TIMEOUT_SECONDS` (20 por defecto, >0 y <=60), sin reintentos. La búsqueda y la generación pueden tener cargos separados según DeepSeek; `402` indica saldo insuficiente y también devuelve `{}`. `sources` contiene las páginas consultadas, no una garantía de verificación por campo. Contrato oficial: https://api-docs.deepseek.com/guides/search .
- **Gemini (opcional):** con `WINE_AUTOCOMPLETE_PROVIDER=gemini`, `GEMINI_AUTOCOMPLETE_WEB_SEARCH=true` por defecto: primero Gemini con la herramienta `google_search` busca fichas (prioriza bodega oficial y después distribuidores). Solo los segmentos enlazados a citas de `grounding_metadata` pasan a una segunda llamada de extracción JSON. Se separan búsqueda y JSON para no exigir soporte simultáneo de herramientas y salida estructurada al modelo. Una discrepancia o identidad/variante incierta debe producir `null`; no existe fallback automático a memoria. La búsqueda reduce, pero no elimina, las identificaciones erróneas.
- Máximo dos llamadas asíncronas, sin reintentos: hasta 1000 tokens de salida para búsqueda y 500 para extracción, temperatura `0.1`, thinking desactivado para `gemini-2.5-flash*`. El contexto de extracción está acotado a 20 segmentos, 6000 caracteres de texto y 16000 caracteres serializados de evidencia, con hasta 10 fuentes. No se descargan URLs desde el backend. Google puede ejecutar varias consultas de búsqueda dentro de la primera llamada, con coste adicional al de los tokens.
- Usa `GEMINI_MODEL` y `GEMINI_API_KEY`; opcionalmente otro modelo con `GEMINI_AUTOCOMPLETE_MODEL` (ausente o vacío hereda `GEMINI_MODEL`). Debe admitir Google Search grounding; si no lo admite, devuelve `{}` en vez de cambiar modelo/proveedor. `GEMINI_REQUEST_TIMEOUT_SECONDS` es el plazo total compartido entre búsqueda y extracción (20 segundos por defecto, configurable entre más de cero y 60); el SDK usa el mismo timeout por petición, limitado por ese plazo global. Un `504` del proveedor puede llegar antes. No envía inventario, historial ni identificadores a Google; solo el nombre. No se persisten sugerencias ni se ejecutan migraciones. Establecer explícitamente `GEMINI_AUTOCOMPLETE_WEB_SEARCH=false` recupera el modo anterior sin búsqueda ni fuentes, menos fiable.
- `sources` contiene `{ "title": "Ficha bodega", "url": "https://..." }`, tomado de los resultados de DeepSeek o los metadatos de Google, nunca de URLs inventadas por el extractor. El frontend debe mostrar estos enlaces junto a las sugerencias, no enviarlos al guardar inventario. Solo Gemini puede agregar `search_suggestions_html`, el Search Entry Point de Google: mostrarlo según las condiciones de Google Search grounding, en un contenedor aislado/sandbox acorde a la política de seguridad del frontend, nunca mediante bypass global de sanitización. No confundir este HTML con un campo de notas del vino.
- No hay caché ni límite de peticiones por cuenta en este endpoint. El frontend debe solicitarlo por acción explícita, evitar peticiones duplicadas y no reintentar automáticamente un `{}`. Las cuotas del proveedor no sustituyen un control de gasto por cuenta.
- El frontend debe mapear `denomination → appellation`, `grape_type → wine_type`, `format → bottle_format`, quitar `%` de `alcohol` antes de guardarlo como `alcohol_percentage`, y convertir los años a `consumption_window`. Los otros nombres coinciden con la API de inventario. No sobrescribir valores introducidos por el usuario con `null`; un `{}` permite continuar la edición manual. No renombrar los campos de persistencia para adaptarlos a este DTO.

Pruebas del autocompletado (Google siempre simulado; los checks de membresía SQL requieren `TEST_DATABASE_URL` y usan esquemas temporales):

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_wine_autocomplete.py -v
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_deepseek_autocomplete.py -v
```

## Contrato compatible y cortocircuito

`POST /api/v1/ai/analyze-stock`, con JWT de usuario y cuerpo:

```json
{"wine_cellar_id":"<uuid>"}
```

Sin opciones nuevas conserva `application/json` y todos los campos anteriores: `id`, `analysis_type`, `content`, `wine_cellar_id`, `tokens_used`, `created_at`. Agrega `status` (`completed` o `empty`) y `message` opcional. El frontend Angular existente puede seguir mostrando `content` sin cambios.

La membresía del espacio y el permiso de análisis (`OWNER`, `SOMMELIER` o `INVENTORY_CLERK`) se verifican antes de leer el inventario. Si hay **cero registros de inventario**, responde inmediatamente `200 application/json`, sin construir prompts, inicializar el SDK ni llamar a Google:

```json
{
  "status": "empty",
  "message": "No hay vinos en esta cava para analizar.",
  "content": "No hay vinos en esta cava para analizar.",
  "tokens_used": 0
}
```

El ejemplo omite los campos de identificación habituales, que también se incluyen. Este cortocircuito también aplica a recomendaciones, reporte mensual y chat. Un registro con cantidad cero sigue siendo información válida para analizar reposición; no equivale a una cava sin registros.

## Streaming opt-in

En el mismo POST, enviar `Accept: text/event-stream` **o** usar `?stream=true`. El backend responde `text/event-stream` cuando hay inventario. Si está vacío, responde el JSON anterior incluso si se pidió streaming: comprobar siempre `Content-Type` antes de consumir el cuerpo.

El streaming es SSE con eventos UTF-8 separados por una línea vacía:

```text
event: delta
data: {"type":"delta","text":"Primera parte del análisis"}

event: delta
data: {"type":"delta","text":" y continuación."}

event: done
data: {"type":"done","result":{"id":"...","analysis_type":"STOCK_ANALYSIS","content":"Primera parte del análisis y continuación.","wine_cellar_id":"...","tokens_used":123,"created_at":"...","status":"completed"}}

```

- `delta.text`: añadir al texto visible inmediatamente.
- `done.result`: resultado final con el contrato JSON habitual; reemplazar el texto provisional con `result.content`. Los tokens pueden ser `null` si el proveedor no los comunica.
- `error`: evento terminal con `code` y `message`. No llega un evento `done` después. Si hubo deltas, mostrar que el análisis quedó incompleto.
- Un cierre sin `done` ni `error` debe tratarse como conexión interrumpida, no como éxito.

Ejemplo de error de cuota después de iniciar SSE:

```text
event: error
data: {"type":"error","code":"rate_limit","message":"La cuota de IA está temporalmente agotada. Inténtalo más tarde."}

```

El frontend necesita `fetch` con POST, JWT y lectura incremental de `response.body`, o un cliente SSE compatible con POST. `EventSource` nativo usa GET y no sirve directamente. El `HttpClient.post<JSON>` actual conserva el modo compatible, pero no muestra deltas en tiempo real.

Al implementar el parser, usar `TextDecoder` en modo incremental y conservar texto incompleto entre lecturas: un chunk HTTP no necesariamente contiene un evento SSE completo y puede dividir caracteres UTF-8. Cancelar mediante `AbortController` al cambiar de cava o destruir el componente. No reintentar automáticamente una petición parcialmente recibida.

Los errores de autenticación/propiedad siguen siendo HTTP `401`/`403` y los recursos ausentes `404`, antes de abrir el stream. Una vez abierto SSE los errores de generación se comunican como evento `error` bajo HTTP `200`; no se pueden cambiar los headers ya enviados.

## Cuota, latencia y configuración

En `.env` (ver `.env.example`):

```dotenv
GEMINI_API_KEY=<clave-local>
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MAX_OUTPUT_TOKENS=500
GEMINI_TEMPERATURE=0.0
GEMINI_REQUEST_TIMEOUT_SECONDS=20
```

Instalar las dependencias actualizadas con `python -m pip install -r requirements.txt`. El adaptador requiere `google-genai>=2.11.0,<3.0`, versión mínima con la que se verificó la configuración del stream y los reintentos del SDK.

- La clave se usa solo en el backend y nunca se devuelve al cliente ni se incluye en logs.
- Máximo efectivo de **500 tokens de salida** y temperatura entre **0.0 y 0.1**, aunque una configuración antigua solicite valores superiores. Se puede reducir el límite de tokens.
- Para modelos `gemini-2.5-flash*` se desactiva thinking (`thinking_budget=0`) y nunca se reenvían bloques de pensamiento.
- El timeout total de generación incluye el reintento y vale 20 segundos por defecto (configurable entre más de cero y 60). La desconexión del cliente cancela el stream y cierra los recursos del proveedor.
- Un único reintento tras 0.5 segundos para `429`, `500`, `502`, `503` o `504`, **solo antes de emitir texto**. Los reintentos internos del SDK están deshabilitados. No se reintentan errores de credenciales/validación ni respuestas parciales.
- En modo JSON, cuota agotada produce `429` con mensaje seguro y `Retry-After: 30`; timeout `504`; servicio/clave ausente `503`. En SSE se usan los códigos `rate_limit`, `timeout`, `not_configured`, `empty_response` o `unavailable` en el evento `error`.
- No se incluyen descripciones de cavas, identificadores o seriales en los prompts de inventario. Hasta 40 registros: solo nombre (acotado), tipo, edad y cantidad. No se inventa una añada a partir de la edad.
- Con más de 40 registros: resumen SQL de totales, rango de edad, hasta 12 tipos y un agregado del resto. No se materializa el inventario completo ni se envía un volcado al LLM.
- Las consultas JSON compatibles también consumen el mismo cliente asíncrono de streaming, acumulando el resultado antes de responder.

No se agregan cachés de respuestas: una consulta con inventario válido sigue consumiendo cuota. Evitar peticiones duplicadas desde el frontend y no asumir que un reintento breve resuelve una cuota diaria agotada.

## Verificación sin consumir cuota

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_inventory_intelligence.py -v
```

Estas pruebas no necesitan clave ni base de datos; simulan los chunks del SDK, errores, timeout y cancelación. Para incluir los checks SQL y el resto de integración con PostgreSQL local:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Las pruebas de base de datos usan esquemas temporales y no ejecutan los seeds de arranque. Ninguna prueba llama a Google. La latencia real del proveedor debe medirse aparte con inventario de prueba y una clave válida; no se garantiza un tiempo de generación específico.
