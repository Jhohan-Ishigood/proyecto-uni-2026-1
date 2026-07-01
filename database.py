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

def _hoja_existe(conn, nombre):
    """Retorna True si la hoja ya existe en el spreadsheet."""
    try:
        df = conn.read(worksheet=nombre, ttl=30)
        return True  # lectura exitosa → hoja existe
    except Exception as e:
        msg = str(e).lower()
        # Si el error es por hoja no encontrada, no existe
        if "not found" in msg or "unable to parse" in msg or "does not exist" in msg:
            return False
        # Cualquier otro error (permisos, red, etc.) asumimos que existe para no borrar datos
        return True

def _asegurar_hoja(conn, nombre, df_inicial):
    """Crea la hoja solo si no existe; silencia el error si ya existe."""
    if _hoja_existe(conn, nombre):
        return
    try:
        conn.create(worksheet=nombre, data=df_inicial)
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg:
            pass  # ya existe, todo bien
        else:
            raise  # re-lanzar errores reales

def inicializar_db(db_path=None):
    """Crea las hojas necesarias en Google Sheets si no existen. Solo se ejecuta una vez por sesión."""
    try:
        conn = get_connection()
        
        FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>"
        
        _asegurar_hoja(conn, "categorias",
            pd.DataFrame({"nombre": ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]}))

        _asegurar_hoja(conn, "productos", pd.DataFrame([
            {"nombre": "Hamburguesa", "precio": 18.0, "icono": "🍔", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 15, "categoria": "Hamburguesas"},
            {"nombre": "Carne a la parrilla", "precio": 35.0, "icono": "🥩", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 10, "categoria": "Parrillas"},
            {"nombre": "Jugo", "precio": 6.0, "icono": "🥤", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 20, "categoria": "Bebidas"},
            {"nombre": "Combo Buffalo", "precio": 25.0, "icono": "🎁", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 8, "categoria": "Combos"}
        ]))

        _asegurar_hoja(conn, "ordenes",
            pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total", "usuario_email"]))

        _asegurar_hoja(conn, "calificaciones",
            pd.DataFrame(columns=["fecha_hora", "nro_boleta", "calificacion", "comentario"]))

        _asegurar_hoja(conn, "logs",
            pd.DataFrame(columns=["fecha_hora", "nivel", "mensaje", "detalle"]))

        _asegurar_hoja(conn, "cupones", pd.DataFrame([
            {"codigo": "BUFFALO10", "tipo": "porcentaje", "valor": 0.10, "descripcion": "10% de descuento", "activo": 1},
            {"codigo": "DELIVERYFREE", "tipo": "delivery", "valor": 6.0, "descripcion": "Delivery gratis", "activo": 1},
            {"codigo": "COMBO5", "tipo": "monto", "valor": 5.0, "descripcion": "S/5.00 de descuento", "activo": 1}
        ]))

        _asegurar_hoja(conn, "usuarios",
            pd.DataFrame(columns=["email", "nombre", "foto", "compras_realizadas", "fecha_registro"]))

        _asegurar_hoja(conn, "mesas",
            pd.DataFrame([{"nro_mesa": i, "estado": "disponible"} for i in range(1, 21)]))

        _asegurar_hoja(conn, "reservas",
            pd.DataFrame(columns=["id", "email", "nombre", "nro_mesa", "fecha", "hora", "datos_contacto", "personas", "nombres_invitados"]))

        _asegurar_hoja(conn, "alertas_salon",
            pd.DataFrame(columns=["fecha_hora", "nro_mesa", "cliente_nombre", "tipo_alerta", "atendido"]))

        st.session_state["_db_inicializada"] = True
    except Exception as e:
        st.error(f"Error al inicializar Google Sheets (Verifica tus secrets y permisos de cuenta de servicio): {e}")


@st.cache_data(ttl=60)
def _obtener_categorias_cached():
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=60)
        if df.empty or "nombre" not in df.columns:
            return []
        return df["nombre"].dropna().astype(str).tolist()
    except Exception:
        return ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]

def obtener_categorias(db_path=None):
    """Obtiene la lista de todas las categorías reales desde Google Sheets."""
    return _obtener_categorias_cached()

def crear_categoria(db_path, nombre):
    """Crea una nueva categoría."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=30)
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
        df_cat = conn.read(worksheet="categorias", ttl=30)
        if not df_cat.empty and "nombre" in df_cat.columns:
            df_cat = df_cat[df_cat["nombre"].astype(str).str.strip() != nombre.strip()]
            conn.update(worksheet="categorias", data=df_cat)
            
        # 2. Actualizar productos asociados para limpiar su categoría
        df_prod = conn.read(worksheet="productos", ttl=30)
        if not df_prod.empty and "categoria" in df_prod.columns:
            df_prod.loc[df_prod["categoria"].astype(str).str.strip() == nombre.strip(), "categoria"] = ""
            conn.update(worksheet="productos", data=df_prod)
    except Exception as e:
        st.error(f"Error eliminando categoría en GSheets: {e}")

@st.cache_data(ttl=300)
def _obtener_menu_cached(ttl=300):
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=ttl)
        if df.empty or "nombre" not in df.columns:
            menu = _obtener_menu_defecto()
        else:
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
                
                # REPARACIÓN AUTOMÁTICA DE IMÁGENES ROTAS:
                # Normalizar texto para verificar si está vacío, es nulo o ruta local inválida
                foto_limpia = str(foto or "").strip()
                if foto_limpia == "nan" or foto_limpia == "None":
                    foto_limpia = ""
                    
                if not foto_limpia or not (foto_limpia.startswith("http://") or foto_limpia.startswith("https://") or foto_limpia.startswith("data:image/")):
                    nom_lower = nombre.lower()
                    if "alita" in nom_lower:
                        foto = "https://images.unsplash.com/photo-1567620832903-9fc6debc209f?w=500&auto=format&fit=crop&q=60"
                    elif "chorizo" in nom_lower:
                        foto = "https://images.unsplash.com/photo-1532246420286-127bcd803104?w=500&auto=format&fit=crop&q=60"
                    elif "anticucho" in nom_lower:
                        foto = "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=500&auto=format&fit=crop&q=60"
                    elif "hamburguesa" in nom_lower:
                        foto = "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500&auto=format&fit=crop&q=60"
                    elif "cerdo" in nom_lower or "puerco" in nom_lower or "chuleta" in nom_lower:
                        # Foto deliciosa de costillas o chuleta de cerdo a la parrilla
                        foto = "https://images.unsplash.com/photo-1544025162-d76694265947?w=500&auto=format&fit=crop&q=60"
                    elif "inka" in nom_lower or "cola" in nom_lower or "gaseosa" in nom_lower or "pepsi" in nom_lower or "coca" in nom_lower or "fanta" in nom_lower or "bebida" in nom_lower or "chicha" in nom_lower:
                        foto = "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?w=500&auto=format&fit=crop&q=60"
                    elif "bufalo" in nom_lower or "parrilla" in nom_lower or "res" in nom_lower or "lomo" in nom_lower or "bife" in nom_lower:
                        # Foto de parrilla premium
                        foto = "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=500&auto=format&fit=crop&q=60"
                    else:
                        # Foto por defecto
                        foto = "https://images.unsplash.com/photo-1544025162-d76694265947?w=500&auto=format&fit=crop&q=60"
                else:
                    foto = foto_limpia
                
                menu[nombre] = {
                    "precio": precio,
                    "icono": icono,
                    "disponible": disponible,
                    "foto": foto,
                    "stock": stock,
                    "categoria": categoria
                }
                
        # Mezclar con productos creados/editados localmente en disco
        import json, os
        prod_resp_path = "productos_respaldo.json"
        if os.path.exists(prod_resp_path):
            try:
                with open(prod_resp_path, "r", encoding="utf-8") as f:
                    locales = json.load(f)  # Diccionario con formato {nombre: {precio, icono, disponible, foto, stock, categoria}}
                    for nombre_l, info_l in locales.items():
                        menu[nombre_l] = info_l
            except Exception:
                pass
                
        return menu
    except Exception:
        # Fallback de emergencia absoluto: si falla el read, retornar el menú en memoria de la sesión
        menu_memoria = st.session_state.get("menu_dinamico")
        if menu_memoria:
            # Mezclar también con locales por si acaso
            import json, os
            prod_resp_path = "productos_respaldo.json"
            if os.path.exists(prod_resp_path):
                try:
                    with open(prod_resp_path, "r", encoding="utf-8") as f:
                        locales = json.load(f)
                        for nombre_l, info_l in locales.items():
                            menu_memoria[nombre_l] = info_l
                except Exception:
                    pass
            return menu_memoria
            
        return _obtener_menu_defecto()

def _obtener_menu_defecto():
    """Retorna un menú de respaldo local precargado con los platos del restaurante."""
    return {
        "PARILLA DE RES": {
            "precio": 30.00,
            "icono": "🥩",
            "disponible": True,
            "foto": "https://images.unsplash.com/photo-1544025162-d76694265947?w=500&auto=format&fit=crop&q=60",
            "stock": 10,
            "categoria": "Parrillas"
        },
        "ALITAS BBQ": {
            "precio": 20.00,
            "icono": "🍗",
            "disponible": True,
            "foto": "https://images.unsplash.com/photo-1567620832903-9fc6debc209f?w=500&auto=format&fit=crop&q=60",
            "stock": 15,
            "categoria": "Parrillas"
        },
        "HAMBURGUESA CLÁSICA": {
            "precio": 15.00,
            "icono": "🍔",
            "disponible": True,
            "foto": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500&auto=format&fit=crop&q=60",
            "stock": 12,
            "categoria": "Hamburguesas"
        },
        "CHICHA MORADA JARRAS": {
            "precio": 12.00,
            "icono": "🥤",
            "disponible": True,
            "foto": "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?w=500&auto=format&fit=crop&q=60",
            "stock": 20,
            "categoria": "Bebidas"
        },
        "COMBO PARRILLERO": {
            "precio": 60.00,
            "icono": "👪",
            "disponible": True,
            "foto": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=500&auto=format&fit=crop&q=60",
            "stock": 5,
            "categoria": "Combos"
        }
    }

def obtener_menu(db_path=None, ttl=TTL_LECTURA):
    """Retorna los productos en un diccionario con la estructura original del menú dinámico."""
    return _obtener_menu_cached(ttl=ttl)

def guardar_producto(db_path, nombre, precio, icono, disponible, foto_ruta, stock, categoria_nombre):
    """Crea o actualiza un producto en Google Sheets."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=30)
        if df.empty or "nombre" not in df.columns:
            df = pd.DataFrame(columns=["nombre", "precio", "icono", "disponible", "foto", "stock", "categoria"])
            
        disponibilidad_val = 1 if disponible else 0
        
        # Verificar si ya existe
        if nombre in df["nombre"].astype(str).values:
            idx = df[df["nombre"].astype(str) == nombre].index[0]
            df.at[idx, "precio"] = _convertir_tipo(precio, "float", default=10.0)
            df.at[idx, "icono"] = _convertir_tipo(icono, "str", default="🍔")
            df.at[idx, "disponible"] = disponibilidad_val
            df.at[idx, "stock"] = _convertir_tipo(stock, "int", default=0)
            df.at[idx, "categoria"] = _convertir_tipo(categoria_nombre, "str", default="")
            if foto_ruta:
                df.at[idx, "foto"] = foto_ruta
        else:
            if not foto_ruta:
                FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>"
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
            
        try:
            conn.update(worksheet="productos", data=df)
            st.cache_data.clear()
        except Exception as e_sheets:
            # Fallback en archivo local en disco en caso de error 429
            import json, os
            prod_resp_path = "productos_respaldo.json"
            
            # Cargar respaldos locales existentes
            locales_dict = {}
            if os.path.exists(prod_resp_path):
                try:
                    with open(prod_resp_path, "r", encoding="utf-8") as f:
                        locales_dict = json.load(f)
                except Exception:
                    pass
            
            # Registrar o actualizar el producto local
            final_foto = foto_ruta if foto_ruta else ("data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>")
            
            locales_dict[nombre] = {
                "precio": float(precio),
                "icono": str(icono or "🍔"),
                "disponible": bool(disponible),
                "foto": final_foto,
                "stock": int(stock),
                "categoria": str(categoria_nombre or "")
            }
            
            try:
                with open(prod_resp_path, "w", encoding="utf-8") as f:
                    json.dump(locales_dict, f, indent=4, ensure_ascii=False)
            except Exception:
                pass
                
            # Actualizar también de inmediato en la sesión del administrador
            if "menu_dinamico" in st.session_state:
                st.session_state.menu_dinamico[nombre] = locales_dict[nombre]
                
            st.cache_data.clear()
            st.toast("⚠️ Conexión saturada: El producto se ha guardado localmente en disco.", icon="💾")
            
        return True
    except Exception as e:
        # Fallback de emergencia si ni siquiera pudimos armar el dataframe
        import json, os
        prod_resp_path = "productos_respaldo.json"
        locales_dict = {}
        if os.path.exists(prod_resp_path):
            try:
                with open(prod_resp_path, "r", encoding="utf-8") as f_err:
                    locales_dict = json.load(f_err)
            except Exception:
                pass
        
        final_foto = foto_ruta if foto_ruta else "🍔"
        locales_dict[nombre] = {
            "precio": float(precio),
            "icono": str(icono or "🍔"),
            "disponible": bool(disponible),
            "foto": final_foto,
            "stock": int(stock),
            "categoria": str(categoria_nombre or "")
        }
        try:
            with open(prod_resp_path, "w", encoding="utf-8") as f_err:
                json.dump(locales_dict, f_err, indent=4, ensure_ascii=False)
        except Exception:
            pass
            
        if "menu_dinamico" in st.session_state:
            st.session_state.menu_dinamico[nombre] = locales_dict[nombre]
            
        st.cache_data.clear()
        st.toast("⚠️ Conexión saturada: El producto se ha guardado localmente.", icon="💾")
        return True

def eliminar_producto(db_path, nombre):
    """Elimina un producto por su nombre."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=30)
        if not df.empty and "nombre" in df.columns:
            df = df[df["nombre"].astype(str) != nombre]
            conn.update(worksheet="productos", data=df)
        return True
    except Exception as e:
        st.error(f"Error eliminando producto de GSheets: {e}")
        return False

@st.cache_data(ttl=300)
def _obtener_ordenes_cached(ttl=300):
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
    """Actualiza el stock de múltiples productos en una sola lectura/escritura con fallback a caché."""
    try:
        conn = get_connection()
        df = None
        try:
            # Intentar lectura directa sin caché
            df = conn.read(worksheet="productos", ttl=30)
        except Exception as e:
            # Fallback en caso de 429: Usar st.session_state.menu_dinamico en memoria libre de red
            menu_cache = st.session_state.get("menu_dinamico")
            if menu_cache:
                rows = []
                for nombre_p, info in menu_cache.items():
                    rows.append({
                        "nombre": nombre_p,
                        "precio": info.get("precio", 10.0),
                        "icono": info.get("icono", "🍔"),
                        "disponible": 1 if info.get("disponible", True) else 0,
                        "foto": info.get("foto", ""),
                        "stock": info.get("stock", 0),
                        "categoria": info.get("categoria", "")
                    })
                df = pd.DataFrame(rows)
            else:
                raise e

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
        df = conn.read(worksheet="calificaciones", ttl=30)
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
        df = conn.read(worksheet="logs", ttl=30)
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
        df = conn.read(worksheet="cupones", ttl=30)
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
        df = conn.read(worksheet="cupones", ttl=30)
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
        df = conn.read(worksheet="cupones", ttl=30)
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
        df = conn.read(worksheet="usuarios", ttl=30)
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
         df = conn.read(worksheet="usuarios", ttl=30)
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
@st.cache_data(ttl=120)
def _obtener_mesas_cached(ttl=120):
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
        df = conn.read(worksheet="mesas", ttl=30)
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
        df = conn.read(worksheet="mesas", ttl=30)
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
        df = conn.read(worksheet="mesas", ttl=30)
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

def obtener_reservas(ttl=30):
    return _obtener_reservas_cached(ttl=ttl)

def crear_reserva(email, nombre, nro_mesa, fecha, hora, datos_contacto, personas, nombres_invitados):
    try:
        conn = get_connection()
        df = conn.read(worksheet="reservas", ttl=30)
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
        df = conn.read(worksheet="reservas", ttl=30)
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
        df = conn.read(worksheet="alertas_salon", ttl=30)
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
        df = conn.read(worksheet="alertas_salon", ttl=30)
        if not df.empty and "nro_mesa" in df.columns:
            df = df[~((df["nro_mesa"].astype(int) == int(nro_mesa)) & (df["tipo_alerta"].astype(str) == str(tipo_alerta)))]
            conn.update(worksheet="alertas_salon", data=df)
            st.cache_data.clear()
            return True
        return False
    except Exception as e:
        st.error(f"Error atendiendo alerta: {e}")
        return False

