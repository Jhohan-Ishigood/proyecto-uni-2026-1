import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import datetime

# Caché de lectura en segundos (evita sobrepasar la cuota de Google Sheets API)
TTL_LECTURA = 600

def get_connection():
    """Retorna la conexión a Google Sheets."""
    return st.connection("gsheets", type=GSheetsConnection)

def _convertir_tipo(valor, tipo, default=None):
    """Función auxiliar para convertir tipos de datos de forma robusta."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return default
    
    valor_str = str(valor).strip()
    if valor_str.lower() == "nan" or valor_str == "":
        return default
    
    try:
        if tipo == "float":
            return float(valor_str)
        elif tipo == "int":
            return int(float(valor_str))
        elif tipo == "bool":
            return valor_str.lower() not in ["0", "false", "no"]
        elif tipo == "str":
            return valor_str
    except (ValueError, TypeError):
        return default
    
    return default

def inicializar_db(db_path=None):
    """Verifica que las hojas necesarias existan en Google Sheets y las crea si no.

    Si falla la conexión (permisos, red, etc.), lo muestra claramente en la interfaz
    para que puedas diagnosticar.
    """
    try:
        conn = get_connection()
        hojas_necesarias = ["categorias", "productos", "ordenes", "calificaciones",
                            "logs", "cupones", "usuarios", "mesas", "reservas", "alertas_salon"]

        FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>"

        dfs_iniciales = {
            "categorias": pd.DataFrame({"nombre": ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]}),
            "productos": pd.DataFrame([
                {"nombre": "Hamburguesa", "precio": 18.0, "icono": "🍔", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 15, "categoria": "Hamburguesas"},
                {"nombre": "Carne a la parrilla", "precio": 35.0, "icono": "🥩", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 10, "categoria": "Parrillas"},
                {"nombre": "Jugo", "precio": 6.0, "icono": "🥤", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 20, "categoria": "Bebidas"},
                {"nombre": "Combo Buffalo", "precio": 25.0, "icono": "🎁", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 8, "categoria": "Combos"}
            ]),
            "ordenes": pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total", "usuario_email"]),
            "calificaciones": pd.DataFrame(columns=["fecha_hora", "nro_boleta", "calificacion", "comentario"]),
            "logs": pd.DataFrame(columns=["fecha_hora", "nivel", "mensaje", "detalle"]),
            "cupones": pd.DataFrame([
                {"codigo": "BUFFALO10", "tipo": "porcentaje", "valor": 0.10, "descripcion": "10% de descuento", "activo": 1},
                {"codigo": "DELIVERYFREE", "tipo": "delivery", "valor": 6.0, "descripcion": "Delivery gratis", "activo": 1},
                {"codigo": "COMBO5", "tipo": "monto", "valor": 5.0, "descripcion": "S/5.00 de descuento", "activo": 1}
            ]),
            "usuarios": pd.DataFrame(columns=["email", "nombre", "foto", "compras_realizadas", "fecha_registro"]),
            "mesas": pd.DataFrame([{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]),
            "reservas": pd.DataFrame(columns=["id", "email", "nombre", "nro_mesa", "fecha", "hora", "datos_contacto", "personas", "nombres_invitados"]),
            "alertas_salon": pd.DataFrame(columns=["fecha_hora", "nro_mesa", "cliente_nombre", "tipo_alerta", "atendido"])
        }

        for nombre_hoja, df_inicial in dfs_iniciales.items():
            try:
                conn.read(worksheet=nombre_hoja, ttl=1)
            except Exception as e:
                msg = str(e).lower()
                if "not found" in msg or "unable to parse" in msg or "does not exist" in msg:
                    try:
                        conn.create(worksheet=nombre_hoja, data=df_inicial)
                        st.info(f"Hoja '{nombre_hoja}' creada automáticamente.")
                    except Exception as e2:
                        if "already exists" not in str(e2).lower():
                            raise e2

        st.session_state["_db_inicializada"] = True
    except Exception as e:
        st.error(f"ERROR DE CONEXIÓN con Google Sheets: {e}")
        st.error("Posibles causas: (1) La cuenta de servicio no tiene acceso al spreadsheet. "
                 "Abre el sheet y compártelo con: streamlit-gsheets@el-gran-bufalo-499616.iam.gserviceaccount.com "
                 "(2) Revisa que el spreadsheet ID en secrets.toml sea correcto.")


@st.cache_data(ttl=60)
def _obtener_categorias_cached():
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=60)
        if df.empty or "nombre" not in df.columns:
            return []
        return df["nombre"].dropna().astype(str).tolist()
    except Exception:
        return []

def obtener_categorias(db_path=None):
    """Obtiene la lista de todas las categorías reales desde Google Sheets."""
    return _obtener_categorias_cached()

def crear_categoria(db_path, nombre):
    """Crea una nueva categoría."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=1)
        if df.empty or "nombre" not in df.columns:
            df = pd.DataFrame(columns=["nombre"])
        
        if nombre.strip() in df["nombre"].dropna().astype(str).str.strip().values:
            return False
            
        new_row = pd.DataFrame([{"nombre": nombre}])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="categorias", data=updated_df)
        return True
    except Exception as e:
        st.error(f"Error creando categoría en GSheets: {e}")
        return False

def eliminar_categoria(db_path, nombre):
    """Elimina una categoría. Los productos asociados tendrán su categoría vacía."""
    try:
        conn = get_connection()
        # 1. Eliminar categoría de la hoja de categorías
        df_cat = conn.read(worksheet="categorias", ttl=1)
        if not df_cat.empty and "nombre" in df_cat.columns:
            df_cat = df_cat[df_cat["nombre"].astype(str).str.strip() != nombre.strip()]
            conn.update(worksheet="categorias", data=df_cat)
            
        # 2. Actualizar productos asociados para limpiar su categoría
        df_prod = conn.read(worksheet="productos", ttl=1)
        if not df_prod.empty and "categoria" in df_prod.columns:
            df_prod.loc[df_prod["categoria"].astype(str).str.strip() == nombre.strip(), "categoria"] = ""
            conn.update(worksheet="productos", data=df_prod)
    except Exception as e:
        st.error(f"Error eliminando categoría en GSheets: {e}")

@st.cache_data(ttl=60)
def _obtener_menu_cached(ttl=60):
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=ttl)
        
        # Normalizar nombres de columnas a minúsculas
        df.columns = [c.strip().lower() for c in df.columns]
        
        if df.empty or "nombre" not in df.columns:
            st.warning(f"La hoja 'productos' está vacía o no tiene columna 'nombre'. Columnas encontradas: {list(df.columns)}")
            return {}
        
        menu = {}
        for _, row in df.iterrows():
            nombre = _convertir_tipo(row.get("nombre"), "str", default=None)
            if not nombre:
                continue
            
            precio = _convertir_tipo(row.get("precio"), "float", default=10.0)
            icono = _convertir_tipo(row.get("icono"), "str", default="🍔")
            disponible = _convertir_tipo(row.get("disponible"), "bool", default=True)
            foto = _convertir_tipo(row.get("foto"), "str", default="")
            stock = _convertir_tipo(row.get("stock"), "int", default=0)
            categoria = _convertir_tipo(row.get("categoria"), "str", default="")
            
            menu[nombre] = {
                "precio": precio,
                "icono": icono,
                "disponible": disponible,
                "foto": foto,
                "stock": stock,
                "categoria": categoria
            }
                
        return menu
    except Exception as e:
        st.error(f"Error leyendo hoja 'productos' de Google Sheets: {e}")
        return {}

def obtener_menu(db_path=None, ttl=TTL_LECTURA):
    """Retorna los productos en un diccionario con la estructura original del menú dinámico."""
    return _obtener_menu_cached(ttl=ttl)

def guardar_producto(db_path, nombre, precio, icono, disponible, foto_ruta, stock, categoria_nombre):
    """Crea o actualiza un producto DIRECTAMENTE en Google Sheets (sin respaldo local)."""
    nombre = nombre.strip()
    FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>"
    
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
        df.columns = [c.strip().lower() for c in df.columns]
        
        if df.empty or "nombre" not in df.columns:
            df = pd.DataFrame(columns=["nombre", "precio", "icono", "disponible", "foto", "stock", "categoria"])
            
        disponibilidad_val = 1 if disponible else 0
        
        # Comparación case-insensitive
        df["nombre_norm"] = df["nombre"].astype(str).str.strip().str.lower()
        nombre_norm = nombre.lower()
        
        if nombre_norm in df["nombre_norm"].values:
            idx = df[df["nombre_norm"] == nombre_norm].index[0]
            df.at[idx, "precio"] = _convertir_tipo(precio, "float", default=10.0)
            df.at[idx, "icono"] = _convertir_tipo(icono, "str", default="🍔")
            df.at[idx, "disponible"] = disponibilidad_val
            df.at[idx, "stock"] = _convertir_tipo(stock, "int", default=0)
            df.at[idx, "categoria"] = _convertir_tipo(categoria_nombre, "str", default="")
            if foto_ruta:
                df.at[idx, "foto"] = foto_ruta
        else:
            if not foto_ruta:
                foto_ruta = FOTO_DEFECTO
                
            new_row = pd.DataFrame([{
                "nombre": nombre,
                "precio": _convertir_tipo(precio, "float", default=10.0),
                "icono": _convertir_tipo(icono, "str", default="🍔"),
                "disponible": disponibilidad_val,
                "foto": foto_ruta,
                "stock": _convertir_tipo(stock, "int", default=0),
                "categoria": _convertir_tipo(categoria_nombre, "str", default="")
            }])
            df = pd.concat([df, new_row], ignore_index=True)
        
        df = df.drop(columns=["nombre_norm"], errors="ignore")
            
        conn.update(worksheet="productos", data=df)
        conn.read(worksheet="productos", ttl=0)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error al guardar en Google Sheets: {e}. Verifica la conexión.")
        return False

def eliminar_producto(db_path, nombre):
    """Elimina un producto por su nombre."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
        if not df.empty and "nombre" in df.columns:
            df = df[df["nombre"].astype(str) != nombre]
            conn.update(worksheet="productos", data=df)
        return True
    except Exception as e:
        st.error(f"Error eliminando producto de GSheets: {e}")
        return False

@st.cache_data(ttl=60)
def _obtener_ordenes_cached(ttl=60):
    try:
        conn = get_connection()
        df = conn.read(worksheet="ordenes", ttl=ttl)
        if df.empty or "nro_boleta" not in df.columns:
            return []
            
        ordenes = []
        df_sorted = df.iloc[::-1]  # Invertir para mostrar las más recientes primero
        for _, row in df_sorted.iterrows():
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
    except Exception:
        return []

def obtener_ordenes(db_path=None, ttl=TTL_LECTURA):
    """Retorna el historial completo de boletas/órdenes, incluyendo respaldos locales."""
    ordenes = _obtener_ordenes_cached(ttl=ttl)
    
    # Cargar y anexar órdenes guardadas localmente en disco por cuota de red
    import json, os
    respaldo_path = "ordenes_respaldo.json"
    if os.path.exists(respaldo_path):
        try:
            with open(respaldo_path, "r", encoding="utf-8") as f:
                locales = json.load(f)
                # Las agregamos al inicio de la lista (las más recientes arriba si invertimos)
                # o al final de la lista. Como _obtener_ordenes_cached ya está invertido (df.iloc[::-1]),
                # agregamos las locales al inicio de la lista para que aparezcan primero
                ordenes = locales + ordenes
        except Exception:
            pass
            
    return ordenes

def crear_orden(db_path, fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total, usuario_email=""):
    """Inserta una nueva orden en el historial de Google Sheets sin agotar la cuota de lectura."""
    try:
        conn = get_connection()
        
        # Leemos de caché local para evitar solicitudes innecesarias al Sheets
        ordenes_locales = obtener_ordenes(ttl=30)
        
        if ordenes_locales:
            # Reconstruir DataFrame mapeado a partir del diccionario de caché
            df = pd.DataFrame(ordenes_locales)
            df = df.rename(columns={
                "Fecha y Hora": "fecha_hora",
                "Nro. Boleta": "nro_boleta",
                "Detalle Artículos": "detalle_articulos",
                "Entrega": "entrega",
                "Método Pago": "metodo_pago",
                "Total": "total",
                "Usuario Email": "usuario_email"
            })
        else:
            # Fallback en caso de que esté vacía la base de datos o falle la conversión
            try:
                df = conn.read(worksheet="ordenes", ttl=30)
            except Exception:
                df = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total", "usuario_email"])

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
        
        updated_df = pd.concat([df, new_row], ignore_index=True)
        try:
            conn.update(worksheet="ordenes", data=updated_df)
            st.cache_data.clear() # Limpiar la caché local para forzar actualización en la bitácora
        except Exception as e:
            # Fallback local en disco en caso de 429
            import json, os
            respaldo_path = "ordenes_respaldo.json"
            nueva_orden_dict = {
                "Fecha y Hora": fecha_hora,
                "Nro. Boleta": nro_boleta,
                "Detalle Artículos": detalle_articulos,
                "Entrega": entrega,
                "Método Pago": metodo_pago,
                "Total": total,
                "Usuario Email": usuario_email
            }
            
            # Cargar órdenes de respaldo existentes
            respaldo_lista = []
            if os.path.exists(respaldo_path):
                try:
                    with open(respaldo_path, "r", encoding="utf-8") as f:
                        respaldo_lista = json.load(f)
                except Exception:
                    pass
            
            respaldo_lista.append(nueva_orden_dict)
            
            try:
                with open(respaldo_path, "w", encoding="utf-8") as f:
                    json.dump(respaldo_lista, f, indent=4, ensure_ascii=False)
            except Exception:
                pass
            
            # Forzar actualización en memoria de la sesión para la bitácora
            if "historial_ordenes" in st.session_state:
                st.session_state.historial_ordenes.append(nueva_orden_dict)
                
            st.toast("⚠️ Conexión saturada: El pedido ha sido guardado localmente de forma segura.", icon="💾")
            
        return True
    except Exception as e:
        print(f"Error registrando orden en GSheets: {e}")
        return False

def actualizar_stock_multiple(db_path, actualizaciones_dict):
    """Actualiza el stock de múltiples productos en Google Sheets."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)

        if df is not None and not df.empty and "nombre" in df.columns:
            for nombre, stock_restante in actualizaciones_dict.items():
                if nombre in df["nombre"].astype(str).values:
                    idx = df[df["nombre"].astype(str) == nombre].index[0]
                    df.at[idx, "stock"] = _convertir_tipo(stock_restante, "int", default=0)
            conn.update(worksheet="productos", data=df)
            st.cache_data.clear() # Limpiar la caché local para forzar actualización visual
            return True
        return False
    except Exception as e:
        print(f"Error actualizando stock en GSheets (se intentó fallback): {e}")
        return False

def actualizar_stock(db_path, nombre, stock_restante):
    return actualizar_stock_multiple(db_path, {nombre: stock_restante})

def crear_calificacion(db_path, fecha_hora, nro_boleta, calificacion, comentario):
    """Registra una calificación del cliente (1-5 estrellas) con comentario opcional."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="calificaciones", ttl=1)
        if df.empty or "nro_boleta" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "calificacion", "comentario"])
        
        new_row = pd.DataFrame([{
            "fecha_hora": fecha_hora,
            "nro_boleta": nro_boleta,
            "calificacion": int(calificacion),
            "comentario": str(comentario or ""),
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="calificaciones", data=df)
        return True
    except Exception as e:
        st.error(f"Error registrando calificación en GSheets: {e}")
        return False

def obtener_calificaciones(db_path=None, ttl=None):
    """Retorna todas las calificaciones registradas."""
    if ttl is None:
        ttl = TTL_LECTURA
    try:
        conn = get_connection()
        df = conn.read(worksheet="calificaciones", ttl=ttl)
        if df.empty or "calificacion" not in df.columns:
            return []
        calificaciones = []
        for _, row in df.iterrows():
            calificaciones.append({
                "fecha_hora": str(row.get("fecha_hora", "")),
                "nro_boleta": str(row.get("nro_boleta", "")),
                "calificacion": int(row.get("calificacion", 0)),
                "comentario": str(row.get("comentario", "")),
            })
        return calificaciones
    except Exception:
        return []

def registrar_log(db_path, fecha_hora, nivel, mensaje, detalle=""):
    """Registra un evento en la hoja de logs para auditoría."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="logs", ttl=1)
        if df.empty or "mensaje" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nivel", "mensaje", "detalle"])
        
        new_row = pd.DataFrame([{
            "fecha_hora": fecha_hora,
            "nivel": str(nivel),
            "mensaje": str(mensaje),
            "detalle": str(detalle or ""),
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="logs", data=df)
        return True
    except Exception:
        return False

# ============================================================================
# FUNCIONES PARA GESTIÓN DE CUPONES
# ============================================================================

def obtener_cupones(ttl=TTL_LECTURA):
    """Retorna los cupones desde Google Sheets como un diccionario."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=ttl)
        if df.empty or "codigo" not in df.columns:
            return {}
            
        cupones = {}
        for _, row in df.iterrows():
            codigo = _convertir_tipo(row.get("codigo"), "str", default=None)
            if not codigo:
                continue
            
            tipo = _convertir_tipo(row.get("tipo"), "str", default="monto")
            valor = _convertir_tipo(row.get("valor"), "float", default=0.0)
            descripcion = _convertir_tipo(row.get("descripcion"), "str", default="")
            activo = _convertir_tipo(row.get("activo"), "bool", default=True)
            
            cupones[codigo] = {
                "tipo": tipo,
                "valor": valor,
                "descripcion": descripcion,
                "activo": activo
            }
        return cupones
    except Exception as e:
        st.error(f"Error obteniendo cupones: {e}")
        return {}

def crear_cupon(codigo, tipo, valor, descripcion, activo=True):
    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=1)
        if df.empty or "codigo" not in df.columns:
            df = pd.DataFrame(columns=["codigo", "tipo", "valor", "descripcion", "activo"])
        
        # Eliminar si existe para reemplazarlo
        df = df[df["codigo"].astype(str).str.strip().str.upper() != codigo.strip().upper()]
        
        new_row = pd.DataFrame([{
            "codigo": codigo.strip().upper(),
            "tipo": tipo,
            "valor": float(valor),
            "descripcion": descripcion,
            "activo": int(activo)
        }])
        
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="cupones", data=updated_df)
        return True
    except Exception as e:
        st.error(f"Error creando cupón: {e}")
        return False

def eliminar_cupon(codigo):
    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=1)
        if not df.empty and "codigo" in df.columns:
            df_filtered = df[df["codigo"].astype(str).str.strip().str.upper() != codigo.strip().upper()]
            conn.update(worksheet="cupones", data=df_filtered)
        return True
    except Exception as e:
        st.error(f"Error eliminando cupón: {e}")
        return False

def actualizar_estado_cupon(codigo, activo):
    try:
        conn = get_connection()
        df = conn.read(worksheet="cupones", ttl=1)
        if not df.empty and "codigo" in df.columns:
            mask = df["codigo"].astype(str).str.strip().str.upper() == codigo.strip().upper()
            if mask.any():
                df.loc[mask, "activo"] = int(activo)
                conn.update(worksheet="cupones", data=df)
        return True
    except Exception as e:
        st.error(f"Error actualizando estado del cupón: {e}")
        return False

# ============================================================================
# FUNCIONES PARA GESTIÓN DE USUARIOS Y FIDELIDAD
# ============================================================================

def obtener_usuario(email):
    try:
        conn = get_connection()
        df = conn.read(worksheet="usuarios", ttl=TTL_LECTURA)
        if df.empty or "email" not in df.columns:
            return None
        
        mask = df["email"].astype(str).str.strip().str.lower() == email.strip().lower()
        if mask.any():
            user_data = df[mask].iloc[0].to_dict()
            return user_data
        return None
    except Exception as e:
        st.error(f"Error obteniendo usuario: {e}")
        return None

def registrar_usuario(email, nombre, foto):
    try:
        usuario_existente = obtener_usuario(email)
        if usuario_existente:
            return False # Ya existe

        conn = get_connection()
        df = conn.read(worksheet="usuarios", ttl=1)
        if df.empty or "email" not in df.columns:
            df = pd.DataFrame(columns=["email", "nombre", "foto", "compras_realizadas", "fecha_registro"])
            
        new_row = pd.DataFrame([{
            "email": email.strip().lower(),
            "nombre": nombre,
            "foto": foto,
            "compras_realizadas": 0,
            "fecha_registro": str(datetime.datetime.now())
        }])
        
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="usuarios", data=updated_df)
        
        # Otorgar cupón de bienvenida automáticamente
        codigo_bienvenida = f"BIENVENIDO-{nombre.split(' ')[0].upper()}"
        crear_cupon(
            codigo=codigo_bienvenida, 
            tipo="porcentaje", 
            valor=0.15, 
            descripcion=f"15% Dcto. por primera vez. Solo para {email}", 
            activo=True
        )
        return codigo_bienvenida
    except Exception as e:
        st.error(f"Error registrando usuario: {e}")
        return False

def incrementar_compra_usuario(email):
    try:
         conn = get_connection()
         df = conn.read(worksheet="usuarios", ttl=1)
         if not df.empty and "email" in df.columns:
             mask = df["email"].astype(str).str.strip().str.lower() == email.strip().lower()
             if mask.any():
                 # Incrementar compras
                 compras_actuales = int(df.loc[mask, "compras_realizadas"].iloc[0] or 0)
                 df.loc[mask, "compras_realizadas"] = compras_actuales + 1
                 conn.update(worksheet="usuarios", data=df)
                 
                 # Sistema de recompensas
                 if (compras_actuales + 1) % 3 == 0:
                     codigo_premio = f"PREMIO{compras_actuales + 1}-{email.split('@')[0].upper()}"
                     crear_cupon(
                         codigo=codigo_premio,
                         tipo="monto",
                         valor=10.0,
                         descripcion=f"S/10 Dcto. por ser cliente frecuente. Para {email}",
                         activo=True
                     )
                     return codigo_premio
         return False
    except Exception as e:
         st.error(f"Error incrementando compra: {e}")
         return False

# ============================================================================
# FUNCIONES DE MESAS
# ============================================================================
@st.cache_data(ttl=60)
def _obtener_mesas_cached(ttl=60):
    try:
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=ttl)
        if df.empty or "nro_mesa" not in df.columns:
            mesas = [{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]
        else:
            mesas = df.to_dict(orient="records")
    except Exception:
        mesas = [{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]
        
    # Aplicar el estado local persistido (fuente de verdad resiliente)
    import json, os
    local_path = "mesas_estado_local.json"
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                estados_locales = json.load(f)  # Diccionario {str(nro): "ocupada"/"disponible"}
                for m in mesas:
                    nro_str = str(m["nro_mesa"])
                    if nro_str in estados_locales:
                        m["estado"] = estados_locales[nro_str]
        except Exception:
            pass
            
    return mesas

def obtener_mesas(ttl=TTL_LECTURA):
    return _obtener_mesas_cached(ttl=ttl)

def actualizar_estado_mesa(nro_mesa, estado):
    # 1. Guardar primero en el archivo local de forma persistente y robusta
    import json, os
    local_path = "mesas_estado_local.json"
    estados_locales = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                estados_locales = json.load(f)
        except Exception:
            pass
            
    estados_locales[str(nro_mesa)] = estado
    
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(estados_locales, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
        
    st.cache_data.clear() # Limpiar cache para forzar recarga visual instantánea en Streamlit
    
    # 2. Intentar actualizar Google Sheets en segundo plano. Si falla (429), no bloqueamos nada
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
        # Silenciamos el error para no romper la experiencia
        return True

def agregar_mesa():
    try:
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=1)
        nueva_mesa = 1
        if not df.empty and "nro_mesa" in df.columns:
            nueva_mesa = int(df["nro_mesa"].max()) + 1
        new_row = pd.DataFrame([{"nro_mesa": nueva_mesa, "estado": "disponible"}])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="mesas", data=updated_df)
        st.cache_data.clear() # Limpiar cache
        return nueva_mesa
    except Exception as e:
        st.error(f"Error agregando mesa: {e}")
        return False

def eliminar_mesa(nro_mesa):
    try:
        conn = get_connection()
        df = conn.read(worksheet="mesas", ttl=1)
        if not df.empty and "nro_mesa" in df.columns:
            df = df[df["nro_mesa"].astype(int) != int(nro_mesa)]
            conn.update(worksheet="mesas", data=df)
            st.cache_data.clear() # Limpiar cache
            return True
        return False
    except Exception as e:
        st.error(f"Error eliminando mesa {nro_mesa}: {e}")
        return False

# ============================================================================
# FUNCIONES DE RESERVAS
# ============================================================================
@st.cache_data(ttl=60)
def _obtener_reservas_cached(ttl=60):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=ttl)
        if df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []

def obtener_reservas(ttl=1):
    return _obtener_reservas_cached(ttl=ttl)

def crear_reserva(email, nombre, nro_mesa, fecha, hora, datos_contacto, personas, nombres_invitados):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=1)
        if df.empty or "id" not in df.columns:
            df = pd.DataFrame(columns=["id", "email", "nombre", "nro_mesa", "fecha", "hora", "datos_contacto", "personas", "nombres_invitados"])
        
        nuevo_id = 1
        if not df.empty and "id" in df.columns:
            # Filtrar nans para el ID max
            valid_ids = df["id"].dropna()
            if not valid_ids.empty:
                nuevo_id = int(valid_ids.astype(float).max()) + 1

        new_row = pd.DataFrame([{
            "id": nuevo_id,
            "email": email.strip().lower(),
            "nombre": nombre,
            "nro_mesa": int(nro_mesa),
            "fecha": str(fecha),
            "hora": str(hora),
            "datos_contacto": str(datos_contacto),
            "personas": int(personas),
            "nombres_invitados": str(nombres_invitados)
        }])
        
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="reservas", data=updated_df)
        st.cache_data.clear() # Limpiar cache para recargar reservas actualizadas
        return nuevo_id
    except Exception as e:
        st.error(f"Error creando reserva: {e}")
        return False

def eliminar_reserva(id_reserva):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=1)
        if not df.empty and "id" in df.columns:
            # Convertir IDs a float/int para evitar problemas de tipos de pandas
            df = df[df["id"].astype(float).astype(int) != int(id_reserva)]
            conn.update(worksheet="reservas", data=df)
            st.cache_data.clear() # Limpiar cache para recargar reservas actualizadas
            return True
        return False
    except Exception as e:
        st.error(f"Error  reserva {id_reserva}: {e}")
        return False


# ============================================================================
# FUNCIONES DE ALERTAS EN SALÓN (LLAMAR MESERO / CUENTA)
# ============================================================================
@st.cache_data(ttl=5)
def _obtener_alertas_cached(ttl=5):
    try:
        conn = get_connection()
        df = conn.read(worksheet="alertas_salon", ttl=ttl)
        if df.empty or "nro_mesa" not in df.columns:
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []

def obtener_alertas(ttl=5):
    return _obtener_alertas_cached(ttl=ttl)

def crear_alerta_salon(nro_mesa, cliente_nombre, tipo_alerta):
    """Crea una alerta de llamado a mesero o cuenta."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="alertas_salon", ttl=1)
        if df.empty or "nro_mesa" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_mesa", "cliente_nombre", "tipo_alerta", "atendido"])

        new_row = pd.DataFrame([{
            "fecha_hora": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "nro_mesa": int(nro_mesa),
            "cliente_nombre": str(cliente_nombre),
            "tipo_alerta": str(tipo_alerta),
            "atendido": 0
        }])
        
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="alertas_salon", data=updated_df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error creando alerta de salón: {e}")
        return False

def atender_alerta_salon(nro_mesa, tipo_alerta):
    """Elimina la alerta de llamado una vez que el mesero la atiende."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="alertas_salon", ttl=1)
        if not df.empty and "nro_mesa" in df.columns:
            df = df[~((df["nro_mesa"].astype(int) == int(nro_mesa)) & (df["tipo_alerta"].astype(str) == str(tipo_alerta)))]
            conn.update(worksheet="alertas_salon", data=df)
            st.cache_data.clear()
            return True
        return False
    except Exception as e:
        st.error(f"Error atendiendo alerta: {e}")
        return False

