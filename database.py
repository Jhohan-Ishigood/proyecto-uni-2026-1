import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import datetime

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

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
    """Convierte un DataFrame de productos a dict menú."""
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

def _df_a_ordenes(df):
    """Convierte un DataFrame de ordenes a lista de dicts."""
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

def _df_a_cupones(df):
    """Convierte un DataFrame de cupones a dict."""
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

def cargar_datos_iniciales():
    """Lee TODOS los datos de Google Sheets UNA SOLA VEZ y los guarda en session state.
    Esta es la ÚNICA función que lee del sheet. Todo lo demás usa session state."""
    if st.session_state.get("_datos_cargados"):
        return

    try:
        conn = get_connection()

        menu = _df_a_menu(conn.read(worksheet="productos"))
        st.session_state["_menu_store"] = menu

        ordenes = _df_a_ordenes(conn.read(worksheet="ordenes"))
        st.session_state["_ordenes_store"] = ordenes

        cupones = _df_a_cupones(conn.read(worksheet="cupones"))
        st.session_state["_cupones_store"] = cupones

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
    FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>"

    menu = st.session_state.get("_menu_store", {})
    menu[nombre] = {
        "precio": _convertir_tipo(precio, "float", default=10.0),
        "icono": _convertir_tipo(icono, "str", default="🍔"),
        "disponible": bool(disponible),
        "foto": foto_ruta or FOTO_DEFECTO,
        "stock": _convertir_tipo(stock, "int", default=0),
        "categoria": _convertir_tipo(categoria_nombre, "str", default="")
    }
    st.session_state["_menu_store"] = menu

    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
        df.columns = [c.strip().lower() for c in df.columns]
        if df.empty or "nombre" not in df.columns:
            df = pd.DataFrame(columns=["nombre", "precio", "icono", "disponible", "foto", "stock", "categoria"])

        for col in ["nombre", "icono", "foto", "categoria"]:
            if col in df.columns:
                df[col] = df[col].astype(object)

        disponibilidad_val = 1 if disponible else 0
        df["nombre_norm"] = df["nombre"].astype(str).str.strip().str.lower()

        if nombre.lower() in df["nombre_norm"].values:
            idx = df[df["nombre_norm"] == nombre.lower()].index[0]
            df.at[idx, "precio"] = _convertir_tipo(precio, "float", default=10.0)
            df.at[idx, "icono"] = _convertir_tipo(icono, "str", default="🍔")
            df.at[idx, "disponible"] = disponibilidad_val
            df.at[idx, "stock"] = _convertir_tipo(stock, "int", default=0)
            df.at[idx, "categoria"] = _convertir_tipo(categoria_nombre, "str", default="")
            if foto_ruta:
                df.at[idx, "foto"] = foto_ruta
        else:
            new_row = pd.DataFrame([{
                "nombre": nombre,
                "precio": _convertir_tipo(precio, "float", default=10.0),
                "icono": _convertir_tipo(icono, "str", default="🍔"),
                "disponible": disponibilidad_val,
                "foto": foto_ruta or FOTO_DEFECTO,
                "stock": _convertir_tipo(stock, "int", default=0),
                "categoria": _convertir_tipo(categoria_nombre, "str", default="")
            }])
            df = pd.concat([df, new_row], ignore_index=True)

        df = df.drop(columns=["nombre_norm"], errors="ignore")
        conn.update(worksheet="productos", data=df)
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_producto(db_path, nombre):
    menu = st.session_state.get("_menu_store", {})
    menu.pop(nombre, None)
    st.session_state["_menu_store"] = menu

    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
        if not df.empty and "nombre" in df.columns:
            df = df[df["nombre"].astype(str) != nombre]
            conn.update(worksheet="productos", data=df)
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── ÓRDENES ────────────────────────────────────────────────────────

def obtener_ordenes(db_path=None, ttl=None):
    return st.session_state.get("_ordenes_store", [])

def crear_orden(db_path, fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total, usuario_email=""):
    nueva_orden = {
        "Fecha y Hora": fecha_hora,
        "Nro. Boleta": nro_boleta,
        "Detalle Artículos": detalle_articulos,
        "Entrega": entrega,
        "Método Pago": metodo_pago,
        "Total": total,
        "Usuario Email": usuario_email
    }

    ordenes = st.session_state.get("_ordenes_store", [])
    ordenes.insert(0, nueva_orden)
    st.session_state["_ordenes_store"] = ordenes

    try:
        conn = get_connection()
        df = conn.read(worksheet="ordenes", ttl=1)
        if df.empty or "nro_boleta" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total", "usuario_email"])

        new_row = pd.DataFrame([{
            "fecha_hora": fecha_hora,
            "nro_boleta": nro_boleta,
            "detalle_articulos": detalle_articulos,
            "entrega": entrega,
            "metodo_pago": metodo_pago,
            "total": total,
            "usuario_email": usuario_email
        }])
        conn.update(worksheet="ordenes", data=pd.concat([df, new_row], ignore_index=True))
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── STOCK ──────────────────────────────────────────────────────────

def actualizar_stock_multiple(db_path, actualizaciones_dict):
    menu = st.session_state.get("_menu_store", {})
    for nombre, stock_restante in actualizaciones_dict.items():
        if nombre in menu:
            menu[nombre]["stock"] = _convertir_tipo(stock_restante, "int", default=0)
    st.session_state["_menu_store"] = menu

    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
        if df is not None and not df.empty and "nombre" in df.columns:
            for nombre, stock_restante in actualizaciones_dict.items():
                if nombre in df["nombre"].astype(str).values:
                    idx = df[df["nombre"].astype(str) == nombre].index[0]
                    df.at[idx, "stock"] = _convertir_tipo(stock_restante, "int", default=0)
            conn.update(worksheet="productos", data=df)
            return True
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def actualizar_stock(db_path, nombre, stock_restante):
    return actualizar_stock_multiple(db_path, {nombre: stock_restante})

# ─── CATEGORÍAS ─────────────────────────────────────────────────────

def crear_categoria(db_path, nombre):
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=1)
        if df.empty or "nombre" not in df.columns:
            df = pd.DataFrame(columns=["nombre"])
        if nombre.strip() in df["nombre"].dropna().astype(str).str.strip().values:
            return False
        conn.update(worksheet="categorias", data=pd.concat([df, pd.DataFrame([{"nombre": nombre}])], ignore_index=True))
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_categoria(db_path, nombre):
    try:
        conn = get_connection()
        df_cat = conn.read(worksheet="categorias", ttl=1)
        if not df_cat.empty and "nombre" in df_cat.columns:
            df_cat = df_cat[df_cat["nombre"].astype(str).str.strip() != nombre.strip()]
            conn.update(worksheet="categorias", data=df_cat)
        df_prod = conn.read(worksheet="productos", ttl=1)
        if not df_prod.empty and "categoria" in df_prod.columns:
            df_prod.loc[df_prod["categoria"].astype(str).str.strip() == nombre.strip(), "categoria"] = ""
            conn.update(worksheet="productos", data=df_prod)
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")

# ─── CALIFICACIONES ─────────────────────────────────────────────────

def crear_calificacion(db_path, fecha_hora, nro_boleta, calificacion, comentario):
    try:
        conn = get_connection()
        df = conn.read(worksheet="calificaciones", ttl=1)
        if df.empty or "nro_boleta" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "calificacion", "comentario"])
        conn.update(worksheet="calificaciones", data=pd.concat([df, pd.DataFrame([{
            "fecha_hora": fecha_hora, "nro_boleta": nro_boleta,
            "calificacion": int(calificacion), "comentario": str(comentario or ""),
        }])], ignore_index=True))
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def obtener_calificaciones(db_path=None, ttl=None):
    try:
        conn = get_connection()
        df = conn.read(worksheet="calificaciones", ttl=1)
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
        conn = get_connection()
        df = conn.read(worksheet="logs", ttl=1)
        if df.empty or "mensaje" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nivel", "mensaje", "detalle"])
        conn.update(worksheet="logs", data=pd.concat([df, pd.DataFrame([{
            "fecha_hora": fecha_hora, "nivel": str(nivel),
            "mensaje": str(mensaje), "detalle": str(detalle or ""),
        }])], ignore_index=True))
        return True
    except Exception:
        return False

# ─── CUPONES ────────────────────────────────────────────────────────

def obtener_cupones(ttl=None):
    return st.session_state.get("_cupones_store", {})

def crear_cupon(codigo, tipo, valor, descripcion, activo=True):
    codigo = codigo.strip().upper()
    cupones = st.session_state.get("_cupones_store", {})
    cupones[codigo] = {
        "tipo": tipo, "valor": float(valor),
        "descripcion": descripcion, "activo": bool(activo)
    }
    st.session_state["_cupones_store"] = cupones

    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=1)
        if df.empty or "codigo" not in df.columns:
            df = pd.DataFrame(columns=["codigo", "tipo", "valor", "descripcion", "activo"])
        df = df[df["codigo"].astype(str).str.strip().str.upper() != codigo]
        conn.update(worksheet="cupones", data=pd.concat([df, pd.DataFrame([{
            "codigo": codigo, "tipo": tipo, "valor": float(valor),
            "descripcion": descripcion, "activo": int(activo)
        }])], ignore_index=True))
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_cupon(codigo):
    codigo = codigo.strip().upper()
    cupones = st.session_state.get("_cupones_store", {})
    cupones.pop(codigo, None)
    st.session_state["_cupones_store"] = cupones

    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=1)
        if not df.empty and "codigo" in df.columns:
            conn.update(worksheet="cupones", data=df[df["codigo"].astype(str).str.strip().str.upper() != codigo])
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def actualizar_estado_cupon(codigo, activo):
    codigo = codigo.strip().upper()
    cupones = st.session_state.get("_cupones_store", {})
    if codigo in cupones:
        cupones[codigo]["activo"] = bool(activo)
        st.session_state["_cupones_store"] = cupones

    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=1)
        if not df.empty and "codigo" in df.columns:
            mask = df["codigo"].astype(str).str.strip().str.upper() == codigo
            if mask.any():
                df.loc[mask, "activo"] = int(activo)
                conn.update(worksheet="cupones", data=df)
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── USUARIOS ───────────────────────────────────────────────────────

def obtener_usuario(email):
    try:
        conn = get_connection()
        df = conn.read(worksheet="usuarios", ttl=1)
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
        conn = get_connection()
        df = conn.read(worksheet="usuarios", ttl=1)
        if df.empty or "email" not in df.columns:
            df = pd.DataFrame(columns=["email", "nombre", "foto", "compras_realizadas", "fecha_registro"])
        conn.update(worksheet="usuarios", data=pd.concat([df, pd.DataFrame([{
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
        conn = get_connection()
        df = conn.read(worksheet="usuarios", ttl=1)
        if not df.empty and "email" in df.columns:
            mask = df["email"].astype(str).str.strip().str.lower() == email.strip().lower()
            if mask.any():
                compras_actuales = int(df.loc[mask, "compras_realizadas"].iloc[0] or 0)
                df.loc[mask, "compras_realizadas"] = compras_actuales + 1
                conn.update(worksheet="usuarios", data=df)
                if (compras_actuales + 1) % 3 == 0:
                    codigo_premio = f"PREMIO{compras_actuales + 1}-{email.split('@')[0].upper()}"
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
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=ttl)
        if df.empty or "nro_mesa" not in df.columns:
            return [{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]
        return df.to_dict(orient="records")
    except Exception:
        return [{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]

def actualizar_estado_mesa(nro_mesa, estado):
    try:
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=1)
        if not df.empty and "nro_mesa" in df.columns:
            mask = df["nro_mesa"].astype(int) == int(nro_mesa)
            if mask.any():
                df.loc[mask, "estado"] = estado
                conn.update(worksheet="mesas", data=df)
                return True
        return False
    except Exception:
        return True

def agregar_mesa():
    try:
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=1)
        nueva_mesa = 1
        if not df.empty and "nro_mesa" in df.columns:
            nueva_mesa = int(df["nro_mesa"].max()) + 1
        conn.update(worksheet="mesas", data=pd.concat([df, pd.DataFrame([{"nro_mesa": nueva_mesa, "estado": "disponible"}])], ignore_index=True))
        return nueva_mesa
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_mesa(nro_mesa):
    try:
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=1)
        if not df.empty and "nro_mesa" in df.columns:
            conn.update(worksheet="mesas", data=df[df["nro_mesa"].astype(int) != int(nro_mesa)])
            return True
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── RESERVAS ───────────────────────────────────────────────────────

def obtener_reservas(ttl=1):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=ttl)
        return [] if df.empty else df.to_dict(orient="records")
    except Exception:
        return []

def crear_reserva(email, nombre, nro_mesa, fecha, hora, datos_contacto, personas, nombres_invitados):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=1)
        if df.empty or "id" not in df.columns:
            df = pd.DataFrame(columns=["id", "email", "nombre", "nro_mesa", "fecha", "hora", "datos_contacto", "personas", "nombres_invitados"])
        nuevo_id = 1
        if not df.empty and "id" in df.columns:
            valid_ids = df["id"].dropna()
            if not valid_ids.empty:
                nuevo_id = int(valid_ids.astype(float).max()) + 1
        conn.update(worksheet="reservas", data=pd.concat([df, pd.DataFrame([{
            "id": nuevo_id, "email": email.strip().lower(), "nombre": nombre,
            "nro_mesa": int(nro_mesa), "fecha": str(fecha), "hora": str(hora),
            "datos_contacto": str(datos_contacto), "personas": int(personas),
            "nombres_invitados": str(nombres_invitados)
        }])], ignore_index=True))
        return nuevo_id
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def eliminar_reserva(id_reserva):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=1)
        if not df.empty and "id" in df.columns:
            conn.update(worksheet="reservas", data=df[df["id"].astype(float).astype(int) != int(id_reserva)])
            return True
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

# ─── ALERTAS SALÓN ──────────────────────────────────────────────────

def obtener_alertas(ttl=5):
    try:
        conn = get_connection()
        df = conn.read(worksheet="alertas_salon", ttl=ttl)
        return [] if df.empty or "nro_mesa" not in df.columns else df.to_dict(orient="records")
    except Exception:
        return []

def crear_alerta_salon(nro_mesa, cliente_nombre, tipo_alerta):
    try:
        conn = get_connection()
        df = conn.read(worksheet="alertas_salon", ttl=1)
        if df.empty or "nro_mesa" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_mesa", "cliente_nombre", "tipo_alerta", "atendido"])
        conn.update(worksheet="alertas_salon", data=pd.concat([df, pd.DataFrame([{
            "fecha_hora": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "nro_mesa": int(nro_mesa), "cliente_nombre": str(cliente_nombre),
            "tipo_alerta": str(tipo_alerta), "atendido": 0
        }])], ignore_index=True))
        return True
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False

def atender_alerta_salon(nro_mesa, tipo_alerta):
    try:
        conn = get_connection()
        df = conn.read(worksheet="alertas_salon", ttl=1)
        if not df.empty and "nro_mesa" in df.columns:
            conn.update(worksheet="alertas_salon", data=df[~((df["nro_mesa"].astype(int) == int(nro_mesa)) & (df["tipo_alerta"].astype(str) == str(tipo_alerta)))])
            return True
        return False
    except Exception as e:
        st.error(f"Google Sheets no disponible: {e}")
        return False
