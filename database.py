import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import datetime

# Caché de lectura en segundos (evita sobrepasar la cuota de Google Sheets API)
TTL_LECTURA = 60

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
    """Crea las hojas necesarias en Google Sheets si no existen. Solo se ejecuta una vez por sesión."""
    # Quitamos el early return para que siempre verifique (es rápido gracias al caché ttl)
    try:
        conn = get_connection()
        
        FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><path d='M8 14s1.5 2 4 2 4-2 4-2'></path><line x1='9' y1='9' x2='9.01' y2='9'></line><line x1='15' y1='9' x2='15.01' y2='9'></line></svg>"
        
        # 1. Asegurar hoja 'categorias'
        try:
            conn.read(worksheet="categorias", ttl=TTL_LECTURA)
        except Exception:
            df_cat = pd.DataFrame({"nombre": ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]})
            conn.create(worksheet="categorias", data=df_cat)
            
        # 2. Asegurar hoja 'productos'
        try:
            conn.read(worksheet="productos", ttl=TTL_LECTURA)
        except Exception:
            productos_defecto = [
                {"nombre": "Hamburguesa", "precio": 18.0, "icono": "🍔", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 15, "categoria": "Hamburguesas"},
                {"nombre": "Carne a la parrilla", "precio": 35.0, "icono": "🥩", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 10, "categoria": "Parrillas"},
                {"nombre": "Jugo", "precio": 6.0, "icono": "🥤", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 20, "categoria": "Bebidas"},
                {"nombre": "Combo Buffalo", "precio": 25.0, "icono": "🎁", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 8, "categoria": "Combos"}
            ]
            df_prod = pd.DataFrame(productos_defecto)
            conn.create(worksheet="productos", data=df_prod)

        # 3. Asegurar hoja 'ordenes'
        try:
            conn.read(worksheet="ordenes", ttl=TTL_LECTURA)
        except Exception:
            df_ord = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total"])
            conn.create(worksheet="ordenes", data=df_ord)
            
        # 4. Asegurar hoja 'calificaciones'
        try:
            conn.read(worksheet="calificaciones", ttl=TTL_LECTURA)
        except Exception:
            df_cal = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "calificacion", "comentario"])
            conn.create(worksheet="calificaciones", data=df_cal)

        # 5. Asegurar hoja 'logs'
        try:
            conn.read(worksheet="logs", ttl=TTL_LECTURA)
        except Exception:
            df_logs = pd.DataFrame(columns=["fecha_hora", "nivel", "mensaje", "detalle"])
            conn.create(worksheet="logs", data=df_logs)
        
        # 6. Asegurar hoja 'cupones'
        try:
            conn.read(worksheet="cupones", ttl=TTL_LECTURA)
        except Exception:
            cupones_defecto = [
                {"codigo": "BUFFALO10", "tipo": "porcentaje", "valor": 0.10, "descripcion": "10% de descuento", "activo": 1},
                {"codigo": "DELIVERYFREE", "tipo": "delivery", "valor": 6.0, "descripcion": "Delivery gratis", "activo": 1},
                {"codigo": "COMBO5", "tipo": "monto", "valor": 5.0, "descripcion": "S/5.00 de descuento", "activo": 1}
            ]
            df_cupones = pd.DataFrame(cupones_defecto)
            conn.create(worksheet="cupones", data=df_cupones)
        
        # 7. Asegurar hoja 'usuarios' (Para Fidelidad / Login)
        try:
            conn.read(worksheet="usuarios", ttl=TTL_LECTURA)
        except Exception:
            df_usuarios = pd.DataFrame(columns=["email", "nombre", "foto", "compras_realizadas", "fecha_registro"])
            conn.create(worksheet="usuarios", data=df_usuarios)
            
        st.session_state["_db_inicializada"] = True
    except Exception as e:
        st.error(f"Error al inicializar Google Sheets (Verifica tus secrets y permisos de cuenta de servicio): {e}")


def obtener_categorias(db_path=None):
    """Obtiene la lista de todas las categorías reales desde Google Sheets."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=TTL_LECTURA)
        if df.empty or "nombre" not in df.columns:
            return []
        return df["nombre"].dropna().astype(str).tolist()
    except Exception as e:
        st.error(f"Error obteniendo categorías de GSheets: {e}")
        return ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]

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

def obtener_menu(db_path=None, ttl=TTL_LECTURA):
    """Retorna los productos en un diccionario con la estructura original del menú dinámico."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=ttl)
        if df.empty or "nombre" not in df.columns:
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
        st.error(f"Error obteniendo menú de GSheets: {e}")
        return {}

def guardar_producto(db_path, nombre, precio, icono, disponible, foto_ruta, stock, categoria_nombre):
    """Crea o actualiza un producto en Google Sheets."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
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
            
        conn.update(worksheet="productos", data=df)
        return True
    except Exception as e:
        st.error(f"Error guardando producto en GSheets: {e}")
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

def obtener_ordenes(db_path=None, ttl=TTL_LECTURA):
    """Retorna el historial completo de boletas/órdenes."""
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
                "Total": _convertir_tipo(row.get("total"), "str", default="")
            })
        return ordenes
    except Exception as e:
        st.error(f"Error obtener_ordenes de GSheets: {e}")
        return []

def crear_orden(db_path, fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total):
    """Inserta una nueva orden en el historial de Google Sheets."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="ordenes", ttl=1)
        if df.empty or "nro_boleta" not in df.columns:
            df = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total"])
            
        new_row = pd.DataFrame([{
            "fecha_hora": fecha_hora,
            "nro_boleta": nro_boleta,
            "detalle_articulos": detalle_articulos,
            "entrega": entrega,
            "metodo_pago": metodo_pago,
            "total": total
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="ordenes", data=df)
        return True
    except Exception as e:
        st.error(f"Error registrando orden en GSheets: {e}")
        return False

def actualizar_stock(db_path, nombre, stock_restante):
    """Actualiza el stock de un producto específico."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=1)
        if not df.empty and "nombre" in df.columns and nombre in df["nombre"].astype(str).values:
            idx = df[df["nombre"].astype(str) == nombre].index[0]
            df.at[idx, "stock"] = _convertir_tipo(stock_restante, "int", default=0)
            conn.update(worksheet="productos", data=df)
            return True
        st.error(f"No se encontró el producto '{nombre}' para actualizar stock.")
        return False
    except Exception as e:
        st.error(f"Error actualizando stock en GSheets: {e}")
        return False

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
        df = conn.read(worksheet="usuarios", ttl=1)
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
