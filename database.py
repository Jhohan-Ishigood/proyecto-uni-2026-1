import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import gspread
import os

def get_connection():
    """Retorna la conexión a Google Sheets."""
    return st.connection("gsheets", type=GSheetsConnection)

def inicializar_db(db_path=None):
    """Crea las hojas necesarias en Google Sheets si no existen."""
    try:
        conn = get_connection()
        client = conn.client
        spreadsheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        spreadsheet = client.open_by_url(spreadsheet_url)
        
        # 1. Asegurar hoja 'categorias'
        try:
            spreadsheet.worksheet("categorias")
        except gspread.exceptions.WorksheetNotFound:
            spreadsheet.add_worksheet(title="categorias", rows="100", cols="2")
            df_cat = pd.DataFrame({"nombre": ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]})
            conn.update(worksheet="categorias", data=df_cat)
            
        # 2. Asegurar hoja 'productos'
        try:
            spreadsheet.worksheet("productos")
        except gspread.exceptions.WorksheetNotFound:
            spreadsheet.add_worksheet(title="productos", rows="100", cols="7")
            FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"
            productos_defecto = [
                {"nombre": "Hamburguesa", "precio": 18.0, "icono": "🍔", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 15, "categoria": "Hamburguesas"},
                {"nombre": "Carne a la parrilla", "precio": 35.0, "icono": "🥩", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 10, "categoria": "Parrillas"},
                {"nombre": "Jugo", "precio": 6.0, "icono": "🥤", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 20, "categoria": "Bebidas"},
                {"nombre": "Combo Buffalo", "precio": 25.0, "icono": "🎁", "disponible": 1, "foto": FOTO_DEFECTO, "stock": 8, "categoria": "Combos"}
            ]
            df_prod = pd.DataFrame(productos_defecto)
            conn.update(worksheet="productos", data=df_prod)

        # 3. Asegurar hoja 'ordenes'
        try:
            spreadsheet.worksheet("ordenes")
        except gspread.exceptions.WorksheetNotFound:
            spreadsheet.add_worksheet(title="ordenes", rows="1000", cols="6")
            df_ord = pd.DataFrame(columns=["fecha_hora", "nro_boleta", "detalle_articulos", "entrega", "metodo_pago", "total"])
            conn.update(worksheet="ordenes", data=df_ord)
    except Exception as e:
        st.error(f"Error al inicializar Google Sheets (Verifica tus secrets y permisos de cuenta de servicio): {e}")

def obtener_categorias(db_path=None):
    """Obtiene la lista de todas las categorías reales desde Google Sheets."""
    try:
        conn = get_connection()
        df = conn.read(worksheet="categorias", ttl=0)
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
        df = conn.read(worksheet="productos", ttl=0)
        if df.empty or "nombre" not in df.columns:
            return {}
            
        menu = {}
        for _, row in df.iterrows():
            nombre = str(row["nombre"]).strip()
            if not nombre or nombre == "nan":
                continue
            
            precio = float(row.get("precio", 0.0))
            icono = str(row.get("icono", "🍔"))
            
            disponibilidad_val = row.get("disponible", 1)
            if isinstance(disponibilidad_val, str):
                disponible = disponibilidad_val.lower() not in ["0", "false", "no"]
            else:
                disponible = bool(disponibilidad_val)
                
            foto = str(row.get("foto", ""))
            if foto == "nan":
                foto = ""
                
            stock = int(row.get("stock", 0)) if pd.notna(row.get("stock")) else 0
            categoria = str(row.get("categoria", ""))
            if categoria == "nan":
                categoria = ""
            
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
            df.at[idx, "precio"] = float(precio)
            df.at[idx, "icono"] = icono
            df.at[idx, "disponible"] = disponibilidad_val
            df.at[idx, "stock"] = int(stock)
            df.at[idx, "categoria"] = categoria_nombre
            if foto_ruta:
                df.at[idx, "foto"] = foto_ruta
        else:
            if not foto_ruta:
                FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"
                foto_ruta = FOTO_DEFECTO
                
            new_row = pd.DataFrame([{
                "nombre": nombre,
                "precio": float(precio),
                "icono": icono,
                "disponible": disponibilidad_val,
                "foto": foto_ruta,
                "stock": int(stock),
                "categoria": categoria_nombre
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
        df = conn.read(worksheet="ordenes", ttl=0)
        if df.empty or "nro_boleta" not in df.columns:
            return []
            
        ordenes = []
        df_sorted = df.iloc[::-1]  # Invertir para mostrar las más recientes primero
        for _, row in df_sorted.iterrows():
            nro_boleta = str(row.get("nro_boleta", ""))
            if not nro_boleta or nro_boleta == "nan":
                continue
                
            ordenes.append({
                "Fecha y Hora": str(row.get("fecha_hora", "")),
                "Nro. Boleta": nro_boleta,
                "Detalle Artículos": str(row.get("detalle_articulos", "")),
                "Entrega": str(row.get("entrega", "")),
                "Método Pago": str(row.get("metodo_pago", "")),
                "Total": str(row.get("total", ""))
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
            df.at[idx, "stock"] = int(stock_restante)
            conn.update(worksheet="productos", data=df)
    except Exception as e:
        st.error(f"Error actualizando stock en GSheets: {e}")
