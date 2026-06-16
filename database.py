import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# Caché de lectura en segundos (evita sobrepasar la cuota de Google Sheets API)
TTL_LECTURA = 10

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
    if st.session_state.get("_db_inicializada", False):
        return
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
        df = conn.read(worksheet="categorias", ttl=0)
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
        df_cat = conn.read(worksheet="categorias", ttl=0)
        if not df_cat.empty and "nombre" in df_cat.columns:
            df_cat = df_cat[df_cat["nombre"].astype(str).str.strip() != nombre.strip()]
            conn.update(worksheet="categorias", data=df_cat)
            
        # 2. Actualizar productos asociados para limpiar su categoría
        df_prod = conn.read(worksheet="productos", ttl=0)
        if not df_prod.empty and "categoria" in df_prod.columns:
            df_prod.loc[df_prod["categoria"].astype(str).str.strip() == nombre.strip(), "categoria"] = ""
            conn.update(worksheet="productos", data=df_prod)
    except Exception as e:
        st.error(f"Error eliminando categoría en GSheets: {e}")

def obtener_menu(db_path=None):
    """Retorna los productos en un diccionario con la estructura original del menú dinámico."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=TTL_LECTURA)
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
        df = conn.read(worksheet="productos", ttl=0)
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
    except Exception as e:
        st.error(f"Error guardando producto en GSheets: {e}")

def eliminar_producto(db_path, nombre):
    """Elimina un producto por su nombre."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=0)
        if not df.empty and "nombre" in df.columns:
            df = df[df["nombre"].astype(str) != nombre]
            conn.update(worksheet="productos", data=df)
    except Exception as e:
        st.error(f"Error eliminando producto de GSheets: {e}")

def obtener_ordenes(db_path=None):
    """Retorna el historial completo de boletas/órdenes."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="ordenes", ttl=TTL_LECTURA)
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
        df = conn.read(worksheet="ordenes", ttl=0)
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
    except Exception as e:
        st.error(f"Error registrando orden en GSheets: {e}")

def actualizar_stock(db_path, nombre, stock_restante):
    """Actualiza el stock de un producto específico."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="productos", ttl=0)
        if not df.empty and "nombre" in df.columns and nombre in df["nombre"].astype(str).values:
            idx = df[df["nombre"].astype(str) == nombre].index[0]
            df.at[idx, "stock"] = _convertir_tipo(stock_restante, "int", default=0)
            conn.update(worksheet="productos", data=df)
    except Exception as e:
        st.error(f"Error actualizando stock en GSheets: {e}")
