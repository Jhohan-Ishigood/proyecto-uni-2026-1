# AGENTS.md — Resumen de Arquitectura

## Problema Resuelto
Error 429 (cuota excedida) en Google Sheets API (60 lecturas/minuto para todo el proyecto).

## Solución: Session State como Caché Permanente

### Flujo de Datos
1. **`database.cargar_datos_iniciales()`** — se ejecuta UNA VEZ al iniciar la sesión. Lee TODAS las hojas (productos + ordenes) y guarda en `st.session_state["_menu_store"]` y `st.session_state["_ordenes_store"]`.
2. **`database.inicializar_db()`** — llama a `cargar_datos_iniciales()`. Marco el `_datos_cargados = True` para no releer.
3. **Todas las funciones de lectura** (`obtener_menu`, `obtener_ordenes`, `obtener_categorias`) leen exclusivamente de `st.session_state`. **Cero** llamadas a la API de Google Sheets.
4. **Todas las funciones de escritura** (`guardar_producto`, `crear_orden`, `actualizar_stock_multiple`, etc.) hacen dos cosas:
   - **Escriben a Google Sheets** (la cuota de escritura es diferente: 100 writes/100s).
   - **Actualizan `st.session_state` inmediatamente** para que la UI refleje el cambio en tiempo real.
5. Si una escritura falla (error de red, etc.), se muestra un error con `st.error()` pero el dato permanece en session state.

### No más `@st.cache_data`
- Eliminamos todos los decoradores `@st.cache_data` (y `st.cache_data.clear()`).
- `@st.cache_data` con TTL forzaba re-lecturas periódicas que sumaban a la cuota.
- En su lugar: session state es el caché; solo se rellena al inicio.

### Admin: Botón "Refrescar"
- En la página de admin hay un botón que fuerza recarga: `st.session_state["_forzar_recarga"] = True`, que en el siguiente ciclo relee `database.obtener_menu()` (que lee de session state — cero API reads). Para forzar una re-lectura real del sheet, se necesitaría: `st.session_state["_datos_cargados"] = False; st.session_state["_menu_store"] = {}; st.session_state["_ordenes_store"] = {}; database.cargar_datos_iniciales()`.

### Archivos Modificados
- **`database.py`**: Reescribir funciones de lectura para usar session state como almacén primario. `cargar_datos_iniciales()` es la única función que lee del sheet. `inicializar_db()` es no-op (solo llama a `cargar_datos_iniciales`). Todas las escrituras actualizan session state + sheet.
- **`app.py`**: Eliminar `st.cache_data.clear()` (líneas 1851 y 2577). Eliminar `ttl=1` en llamadas a funciones de lectura (no aplica porque no hay `@st.cache_data`). Simplificar bloque de carga inicial (solo llena session state, no relee).

### Verificación
- Productos cargados: `database.obtener_menu()` devuelve dict con nombres y precios.
- Cero llamadas a Google Sheets en lectura después del startup.
