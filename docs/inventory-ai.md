# Análisis de inventario con IA

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
