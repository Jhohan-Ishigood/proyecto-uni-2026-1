import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import datetime
import time

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def _raw_update(conn, worksheet, data):
    conn.update(worksheet=worksheet, data=data)

def _escribir_con_reintento(worksheet, data, max_reintentos=3):
    for intento in range(max_reintentos):
        try:
            conn = get_connection()
            _raw_update(conn, worksheet, data)
            if isinstance(data, pd.DataFrame):
                st.session_state[f"_sheet_cache_{worksheet}"] = data.copy()
                st.session_state[f"_sheet_cache_ts_{worksheet}"] = time.time()
            return True
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if intento < max_reintentos - 1:
                    time.sleep(2 ** intento)
                    continue
            st.error(f"Google Sheets no disponible: {e}")
            return False
    return False

def _leer_sheet(worksheet, ttl=60):
    cache_key = f"_sheet_cache_{worksheet}"
    ts_key = f"_sheet_cache_ts_{worksheet}"
    ahora = time.time()
    ttl_segundos = 60 if ttl is None else max(int(ttl), 30)

    if cache_key in st.session_state and ahora - st.session_state.get(ts_key, 0) < ttl_segundos:
        return st.session_state[cache_key].copy()

    conn = get_connection()
    df = conn.read(worksheet=worksheet, ttl=ttl_segundos)
    st.session_state[cache_key] = df.copy()
    st.session_state[ts_key] = ahora
    return df

def _convertir_tipo(valor, tipo, default=None):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return default
    valor_str = str(valor).strip()
    if valor_str.lower() == "nan" or valor_str == "":
        return default
    try:
        if tipo == "float":     return float(valor_str)
        elif tipo == "int":     return int(float(valor_str))
        elif tipo == "bool":    return valor_str.lower() not in ["0", "false", "no"]
        elif tipo == "str":     return valor_str
    except (ValueError, TypeError):
        return default
    return default

def _df_a_menu(df):
    df.columns = [c.strip().lower() for c in df.columns]
    menu = {}
    for _, row in df.iterrows():
        nombre = _convertir_tipo(row.get("nombre"), "str", default=None)
        if not nombre:
            continue
        menu[nombre] = {
            "precio": _convertir_tipo(row.get("precio"), "float", default=10.0),
            "icono": _convertir_tipo(row.get("icono"), "str", default="🍔"),
            "disponible": _convertir_tipo(row.get("disponible"), "bool", default=True),
            "foto": _convertir_tipo(row.get("foto"), "str", default=""),
            "stock": _convertir_tipo(row.get("stock"), "int", default=0),
            "categoria": _convertir_tipo(row.get("categoria"), "str", default="")
        }
    return menu

def _menu_a_df(menu):
    rows = []
    for nombre, info in menu.items():
        rows.append({
            "nombre": nombre,
            "precio": info.get("precio", 0),
            "icono": info.get("icono", ""),
            "disponible": 1 if info.get("disponible", True) else 0,
            "foto": info.get("foto", ""),
            "stock": info.get("stock", 0),
            "categoria": info.get("categoria", "")
        })
    return pd.DataFrame(rows)

def _df_a_ordenes(df):
    if df.empty or "nro_boleta" not in df.columns:
        return []
    ordenes = []
    for _, row in df.iloc[::-1].iterrows():
        nro_boleta = _convertir_tipo(row.get("nro_boleta"), "str", default=None)
        if not nro_boleta:
            continue
        ordenes.append({
            "Fecha y Hora": _convertir_tipo(row.get("fecha_hora"), "str", default=""),
            "Nro. Boleta": nro_boleta,
            "Detalle Artículos": _convertir_tipo(row.get("detalle_articulos"), "str", default=""),
            "Entrega": _convertir_tipo(row.get("entrega"), "str", default=""),
            "Método Pago": _convertir_tipo(row.get("metodo_pago"), "str", default=""),
            "Total": _convertir_tipo(row.get("total"), "str", default=""),
            "Usuario Email": _convertir_tipo(row.get("usuario_email"), "str", default="")
        })
    return ordenes

def _ordenes_a_df(ordenes):
    rows = []
    for o in ordenes:
        rows.append({
            "fecha_hora": o.get("Fecha y Hora", ""),
            "nro_boleta": o.get("Nro. Boleta", ""),
            "detalle_articulos": o.get("Detalle Artículos", ""),
            "entrega": o.get("Entrega", ""),
            "metodo_pago": o.get("Método Pago", ""),
            "total": o.get("Total", ""),
            "usuario_email": o.get("Usuario Email", "")
        })
    return pd.DataFrame(rows)

def _df_a_cupones(df):
    if df.empty or "codigo" not in df.columns:
        return {}
    cupones = {}
    for _, row in df.iterrows():
        codigo = _convertir_tipo(row.get("codigo"), "str", default=None)
        if not codigo:
            continue
        cupones[codigo] = {
            "tipo": _convertir_tipo(row.get("tipo"), "str", default="monto"),
            "valor": _convertir_tipo(row.get("valor"), "float", default=0.0),
            "descripcion": _convertir_tipo(row.get("descripcion"), "str", default=""),
            "activo": _convertir_tipo(row.get("activo"), "bool", default=True)
        }
    return cupones

def _cupones_a_df(cupones):
    rows = []
    for codigo, info in cupones.items():
        rows.append({
            "codigo": codigo,
            "tipo": info.get("tipo", ""),
            "valor": info.get("valor", 0),
            "descripcion": info.get("descripcion", ""),
            "activo": 1 if info.get("activo", True) else 0
        })
    return pd.DataFrame(rows)

def cargar_datos_iniciales():
    if st.session_state.get("_datos_cargados"):
        return
    try:
        conn = get_connection()
        st.session_state["_menu_store"] = _df_a_menu(conn.read(worksheet="productos"))
        st.session_state["_ordenes_store"] = _df_a_ordenes(conn.read(worksheet="ordenes"))
        st.session_state["_cupones_store"] = _df_a_cupones(conn.read(worksheet="cupones"))
        st.session_state["_datos_cargados"] = True
    except Exception as e:
        st.error(f"Error cargando datos de Google Sheets: {e}")

def inicializar_db(db_path=None):
    cargar_datos_iniciales()

# ─── MENÚ / PRODUCTOS ───────────────────────────────────────────────

def obtener_menu(db_path=None, ttl=None):
    return st.session_state.get("_menu_store", {})

def obtener_categorias(db_path=None):
    menu = obtener_menu()
    cats = set()
    for info in menu.values():
        c = info.get("categoria", "").strip()
        if c:
            cats.add(c)
    return sorted(cats)

def guardar_producto(db_path, nombre, precio, icono, disponible, foto_ruta, stock, categoria_nombre):
    nombre = nombre.strip()
    menu = st.session_state.get("_menu_store", {})
    menu[nombre] = {
        "precio": _convertir_tipo(precio, "float", default=10.0),
        "icono": _convertir_tipo(icono, "str", default="🍔"),
        "disponible": bool(disponible),
        "foto": menu.get(nombre, {}).get("foto", "") if foto_ruta is None else foto_ruta,
        "stock": _convertir_tipo(stock, "int", default=0),
        "categoria": _convertir_tipo(categoria_nombre, "str", default="")
    }
    st.session_state["_menu_store"] = menu
    df = _menu_a_df(menu)
    return _escribir_con_reintento(worksheet="productos", data=df)

def eliminar_producto(db_path, nombre):
    menu = st.session_state.get("_menu_store", {})
    menu.pop(nombre, None)
    st.session_state["_menu_store"] = menu
    df = _menu_a_df(menu)
    return _escribir_con_reintento(worksheet="productos", data=df)

# ─── ÓRDENES ────────────────────────────────────────────────────────

def obtener_ordenes(db_path=None, ttl=None):
    return st.session_state.get("_ordenes_store", [])

def crear_orden(db_path, fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total, usuario_email=""):
    nueva_orden = {
        "Fecha y Hora": fecha_hora, "Nro. Boleta": nro_boleta,
        "Detalle Artículos": detalle_articulos, "Entrega": entrega,
        "Método Pago": metodo_pago, "Total": total, "Usuario Email": usuario_email
    }
    ordenes = st.session_state.get("_ordenes_store", [])
    ordenes.insert(0, nueva_orden)
    st.session_state["_ordenes_store"] = ordenes
    df = _ordenes_a_df(ordenes)
    return _escribir_con_reintento(worksheet="ordenes", data=df)

# ─── STOCK ──────────────────────────────────────────────────────────

def actualizar_stock_multiple(db_path, actualizaciones_dict):
    menu = st.session_state.get("_menu_store", {})
    for nombre, stock_restante in actualizaciones_dict.items():
        if nombre in menu:
            menu[nombre]["stock"] = _convertir_tipo(stock_restante, "int", default=0)
    st.session_state["_menu_store"] = menu
    df = _menu_a_df(menu)
    return _escribir_con_reintento(worksheet="productos", data=df)

def actualizar_stock(db_path, nombre, stock_restante):
    return actualizar_stock_multiple(db_path, {nombre: stock_restante})

# ─── CATEGORÍAS ─────────────────────────────────────────────────────

def crear_categoria(db_path, nombre):
    try:
        df = _leer_sheet("categorias")
        if df.empty or "nombre" not in df.columns:
            df = pd.DataFrame(columns=["nombre"])
        if nombre.strip() in df["nombre"].dropna().astype(str).str.strip().values:
            return False
        return _escribir_con_reintento(worksheet="categorias", data=pd.concat([df, pd.DataFrame([{"nombre": nombre}])], ignore_index=True))
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_categoria(db_path, nombre):
    try:
        df_cat = _leer_sheet("categorias")
        if not df_cat.empty and "nombre" in df_cat.columns:
            df_cat = df_cat[df_cat["nombre"].astype(str).str.strip() != nombre.strip()]
            _escribir_con_reintento(worksheet="categorias", data=df_cat)
        df_prod = _leer_sheet("productos")
        if not df_prod.empty and "categoria" in df_prod.columns:
            df_prod.loc[df_prod["categoria"].astype(str).str.strip() == nombre.strip(), "categoria"] = ""
            _escribir_con_reintento(worksheet="productos", data=df_prod)
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")

# ─── CALIFICACIONES ─────────────────────────────────────────────────

def crear_calificacion(db_path, fecha_hora, nro_boleta, calificacion, comentario):
    try:
        df = _leer_sheet("calificaciones")
        if df.empty or "nro_boleta" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "calificacion", "comentario"])
        return _escribir_con_reintento(worksheet="calificaciones", data=pd.concat([df, pd.DataFrame([{
            "fecha_hora": fecha_hora, "nro_boleta": nro_boleta,
            "calificacion": int(calificacion), "comentario": str(comentario or ""),
        }])], ignore_index=True))
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def obtener_calificaciones(db_path=None, ttl=None):
    try:
        df = _leer_sheet("calificaciones")
        if df.empty or "calificacion" not in df.columns:
            return []
        return [{"fecha_hora": str(r.get("fecha_hora", "")), "nro_boleta": str(r.get("nro_boleta", "")),
                 "calificacion": int(r.get("calificacion", 0)), "comentario": str(r.get("comentario", ""))}
                for _, r in df.iterrows()]
    except Exception:
        return []

# ─── LOGS ───────────────────────────────────────────────────────────

def registrar_log(db_path, fecha_hora, nivel, mensaje, detalle=""):
    try:
        df = _leer_sheet("logs")
        if df.empty or "mensaje" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nivel", "mensaje", "detalle"])
        return _escribir_con_reintento(worksheet="logs", data=pd.concat([df, pd.DataFrame([{
            "fecha_hora": fecha_hora, "nivel": str(nivel),
            "mensaje": str(mensaje), "detalle": str(detalle or ""),
        }])], ignore_index=True))
    except Exception:
        return False

# ─── CUPONES ────────────────────────────────────────────────────────

def obtener_cupones(ttl=None):
    return st.session_state.get("_cupones_store", {})

def crear_cupon(codigo, tipo, valor, descripcion, activo=True):
    codigo = codigo.strip().upper()
    cupones = st.session_state.get("_cupones_store", {})
    cupones[codigo] = {"tipo": tipo, "valor": float(valor), "descripcion": descripcion, "activo": bool(activo)}
    st.session_state["_cupones_store"] = cupones
    df = _cupones_a_df(cupones)
    return _escribir_con_reintento(worksheet="cupones", data=df)

def eliminar_cupon(codigo):
    codigo = codigo.strip().upper()
    cupones = st.session_state.get("_cupones_store", {})
    cupones.pop(codigo, None)
    st.session_state["_cupones_store"] = cupones
    df = _cupones_a_df(cupones)
    return _escribir_con_reintento(worksheet="cupones", data=df)

def actualizar_estado_cupon(codigo, activo):
    codigo = codigo.strip().upper()
    cupones = st.session_state.get("_cupones_store", {})
    cupones[codigo] = {**cupones.get(codigo, {}), "activo": bool(activo)}
    st.session_state["_cupones_store"] = cupones
    df = _cupones_a_df(cupones)
    return _escribir_con_reintento(worksheet="cupones", data=df)

# ─── USUARIOS ───────────────────────────────────────────────────────

def obtener_usuario(email):
    try:
        df = _leer_sheet("usuarios")
        if df.empty or "email" not in df.columns:
            return None
        mask = df["email"].astype(str).str.strip().str.lower() == email.strip().lower()
        return df[mask].iloc[0].to_dict() if mask.any() else None
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return None

def registrar_usuario(email, nombre, foto):
    try:
        if obtener_usuario(email):
            return False
        df = _leer_sheet("usuarios")
        if df.empty or "email" not in df.columns:
            df = pd.DataFrame(columns=["email", "nombre", "foto", "compras_realizadas", "fecha_registro"])
        _escribir_con_reintento(worksheet="usuarios", data=pd.concat([df, pd.DataFrame([{
            "email": email.strip().lower(), "nombre": nombre, "foto": foto,
            "compras_realizadas": 0, "fecha_registro": str(datetime.datetime.now())
        }])], ignore_index=True))
        codigo_bienvenida = f"BIENVENIDO-{nombre.split(' ')[0].upper()}"
        crear_cupon(codigo=codigo_bienvenida, tipo="porcentaje", valor=0.15,
                    descripcion=f"15% Dcto. por primera vez. Solo para {email}", activo=True)
        return codigo_bienvenida
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def incrementar_compra_usuario(email):
    try:
        df = _leer_sheet("usuarios")
        if not df.empty and "email" in df.columns:
            mask = df["email"].astype(str).str.strip().str.lower() == email.strip().lower()
            if mask.any():
                compras_actuales = int(df.loc[mask, "compras_realizadas"].iloc[0] or 0)
                df.loc[mask, "compras_realizadas"] = compras_actuales + 1
                _escribir_con_reintento(worksheet="usuarios", data=df)
                if (compras_actuales + 1) % 3 == 0:
                    codigo_premio = f"PREMIO{compras_actuales+1}-{email.split('@')[0].upper()}"
                    crear_cupon(codigo=codigo_premio, tipo="monto", valor=10.0,
                                descripcion=f"S/10 Dcto. por ser cliente frecuente. Para {email}", activo=True)
                    return codigo_premio
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── MESAS ──────────────────────────────────────────────────────────

def obtener_mesas(ttl=1):
    try:
        df = _leer_sheet("mesas", ttl=ttl)
        if df.empty or "nro_mesa" not in df.columns:
            return [{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]
        return df.to_dict(orient="records")
    except Exception:
        return [{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]

def actualizar_estado_mesa(nro_mesa, estado):
    try:
        df = _leer_sheet("mesas")
        if not df.empty and "nro_mesa" in df.columns:
            mask = df["nro_mesa"].astype(int) == int(nro_mesa)
            if mask.any():
                df.loc[mask, "estado"] = estado
                _escribir_con_reintento(worksheet="mesas", data=df)
                return True
        return False
    except Exception:
        return True

def agregar_mesa():
    try:
        df = _leer_sheet("mesas")
        nueva_mesa = 1
        if not df.empty and "nro_mesa" in df.columns:
            nueva_mesa = int(df["nro_mesa"].max()) + 1
        _escribir_con_reintento(worksheet="mesas", data=pd.concat([df, pd.DataFrame([{"nro_mesa": nueva_mesa, "estado": "disponible"}])], ignore_index=True))
        return nueva_mesa
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_mesa(nro_mesa):
    try:
        df = _leer_sheet("mesas")
        if not df.empty and "nro_mesa" in df.columns:
            _escribir_con_reintento(worksheet="mesas", data=df[df["nro_mesa"].astype(int) != int(nro_mesa)])
            return True
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── RESERVAS ───────────────────────────────────────────────────────

def obtener_reservas(ttl=1):
    try:
        df = _leer_sheet("reservas", ttl=ttl)
        return [] if df.empty else df.to_dict(orient="records")
    except Exception:
        return []

def crear_reserva(email, nombre, nro_mesa, fecha, hora, datos_contacto, personas, nombres_invitados):
    try:
        df = _leer_sheet("reservas")
        if df.empty or "id" not in df.columns:
            df = pd.DataFrame(columns=["id", "email", "nombre", "nro_mesa", "fecha", "hora", "datos_contacto", "personas", "nombres_invitados"])
        nuevo_id = 1
        if not df.empty and "id" in df.columns:
            valid_ids = df["id"].dropna()
            if not valid_ids.empty:
                nuevo_id = int(valid_ids.astype(float).max()) + 1
        return _escribir_con_reintento(worksheet="reservas", data=pd.concat([df, pd.DataFrame([{
            "id": nuevo_id, "email": email.strip().lower(), "nombre": nombre,
            "nro_mesa": int(nro_mesa), "fecha": str(fecha), "hora": str(hora),
            "datos_contacto": str(datos_contacto), "personas": int(personas),
            "nombres_invitados": str(nombres_invitados)
        }])], ignore_index=True))
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_reserva(id_reserva):
    try:
        df = _leer_sheet("reservas")
        if not df.empty and "id" in df.columns:
            return _escribir_con_reintento(worksheet="reservas", data=df[df["id"].astype(float).astype(int) != int(id_reserva)])
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── ALERTAS SALÓN ──────────────────────────────────────────────────

def obtener_alertas(ttl=None):
    ahora = time.time()
    ultima = st.session_state.get("_alertas_ts", 0)
    if ahora - ultima < 5:
        return st.session_state.get("_alertas_cache", [])
    try:
        df = _leer_sheet("alertas_salon", ttl=0)
        alertas = [] if df.empty or "nro_mesa" not in df.columns else df.to_dict(orient="records")
        st.session_state["_alertas_cache"] = alertas
        st.session_state["_alertas_ts"] = ahora
        return alertas
    except Exception:
        return st.session_state.get("_alertas_cache", [])

def crear_alerta_salon(nro_mesa, cliente_nombre, tipo_alerta):
    try:
        df = _leer_sheet("alertas_salon")
        if df.empty or "nro_mesa" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_mesa", "cliente_nombre", "tipo_alerta", "atendido"])
        return _escribir_con_reintento(worksheet="alertas_salon", data=pd.concat([df, pd.DataFrame([{
            "fecha_hora": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "nro_mesa": int(nro_mesa), "cliente_nombre": str(cliente_nombre),
            "tipo_alerta": str(tipo_alerta), "atendido": 0
        }])], ignore_index=True))
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def atender_alerta_salon(nro_mesa, tipo_alerta):
    try:
        df = _leer_sheet("alertas_salon")
        if not df.empty and "nro_mesa" in df.columns:
            return _escribir_con_reintento(worksheet="alertas_salon", data=df[~((df["nro_mesa"].astype(int) == int(nro_mesa)) & (df["tipo_alerta"].astype(str) == str(tipo_alerta)))])
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False
