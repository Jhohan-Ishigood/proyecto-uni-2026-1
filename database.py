import sqlite3
import os

def get_connection(db_path):
    """Retorna una conexión a SQLite habilitando soporte para llaves foráneas."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def inicializar_db(db_path):
    """Crea las tablas necesarias en la base de datos si no existen."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # 1. Tabla de Categorías
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL
    );
    """)
    
    # 2. Tabla de Subcategorías
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subcategorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL,
        categoria_id INTEGER NOT NULL,
        FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
    );
    """)
    
    # 3. Tabla de Productos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL,
        precio REAL NOT NULL,
        icono TEXT NOT NULL,
        disponible INTEGER NOT NULL DEFAULT 1,
        foto TEXT,
        stock INTEGER NOT NULL DEFAULT 0,
        categoria_id INTEGER,
        subcategoria_id INTEGER,
        FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL,
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id) ON DELETE SET NULL
    );
    """)
    
    # 4. Tabla de Órdenes (Historial)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ordenes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_hora TEXT NOT NULL,
        nro_boleta TEXT UNIQUE NOT NULL,
        detalle_articulos TEXT NOT NULL,
        entrega TEXT NOT NULL,
        metodo_pago TEXT NOT NULL,
        total TEXT NOT NULL
    );
    """)
    
    conn.commit()
    conn.close()
    
    # Sembrar datos por defecto si la base de datos está vacía
    sembrar_datos_iniciales(db_path)

def sembrar_datos_iniciales(db_path):
    """Inserta las categorías y productos por defecto si no existen en la base de datos."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Verificar si ya existen categorías
    cursor.execute("SELECT COUNT(*) FROM categorias")
    if cursor.fetchone()[0] == 0:
        # Categorías por defecto (excluyendo "Todos" que se maneja de forma virtual en la UI)
        categorias_defecto = ["Parrillas", "Hamburguesas", "Bebidas", "Combos"]
        for cat in categorias_defecto:
            cursor.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (cat,))
        conn.commit()
        
    # Verificar si ya existen productos
    cursor.execute("SELECT COUNT(*) FROM productos")
    if cursor.fetchone()[0] == 0:
        FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"
        
        productos_defecto = [
            ("Hamburguesa", 18.0, "🍔", 1, FOTO_DEFECTO, 15, "Hamburguesas"),
            ("Carne a la parrilla", 35.0, "🥩", 1, FOTO_DEFECTO, 10, "Parrillas"),
            ("Jugo", 6.0, "🥤", 1, FOTO_DEFECTO, 20, "Bebidas"),
            ("Combo Buffalo", 25.0, "🎁", 1, FOTO_DEFECTO, 8, "Combos")
        ]
        
        for nombre, precio, icono, disponible, foto, stock, cat_nombre in productos_defecto:
            # Obtener el id de la categoría asociada
            cursor.execute("SELECT id FROM categorias WHERE nombre = ?", (cat_nombre,))
            cat_row = cursor.fetchone()
            cat_id = cat_row[0] if cat_row else None
            
            cursor.execute("""
            INSERT OR IGNORE INTO productos (nombre, precio, icono, disponible, foto, stock, categoria_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (nombre, precio, icono, disponible, foto, stock, cat_id))
        conn.commit()
        
    conn.close()

def obtener_categorias(db_path):
    """Obtiene la lista de todas las categorías reales desde la base de datos."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM categorias ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def crear_categoria(db_path, nombre):
    """Crea una nueva categoría."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    exito = False
    try:
        cursor.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
        conn.commit()
        exito = True
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()
    return exito

def eliminar_categoria(db_path, nombre):
    """Elimina una categoría. Los productos asociados tendrán su categoria_id como NULL."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categorias WHERE nombre = ?", (nombre,))
    conn.commit()
    conn.close()

def obtener_menu(db_path):
    """Retorna los productos en un diccionario con la estructura original del menú dinámico."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.nombre, p.precio, p.icono, p.disponible, p.foto, p.stock, c.nombre
        FROM productos p
        LEFT JOIN categorias c ON p.categoria_id = c.id
    """)
    rows = cursor.fetchall()
    conn.close()
    
    menu = {}
    for row in rows:
        nombre, precio, icono, disponible, foto, stock, cat_nombre = row
        menu[nombre] = {
            "precio": float(precio),
            "icono": icono,
            "disponible": bool(disponible),
            "foto": foto if foto else "",
            "stock": int(stock),
            "categoria": cat_nombre if cat_nombre else ""
        }
    return menu

def guardar_producto(db_path, nombre, precio, icono, disponible, foto_ruta, stock, categoria_nombre):
    """Crea o actualiza un producto en la base de datos."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Obtener el ID de la categoría
    cursor.execute("SELECT id FROM categorias WHERE nombre = ?", (categoria_nombre,))
    cat_row = cursor.fetchone()
    cat_id = cat_row[0] if cat_row else None
    
    # Verificar si el producto ya existe
    cursor.execute("SELECT id FROM productos WHERE nombre = ?", (nombre,))
    prod_row = cursor.fetchone()
    
    if prod_row:
        # Actualización
        if foto_ruta:  # Si se especificó una nueva foto/ruta
            cursor.execute("""
                UPDATE productos 
                SET precio = ?, icono = ?, disponible = ?, foto = ?, stock = ?, categoria_id = ?
                WHERE nombre = ?
            """, (precio, icono, int(disponible), foto_ruta, stock, cat_id, nombre))
        else:
            # Si no se pasó foto_ruta, se mantiene la actual
            cursor.execute("""
                UPDATE productos 
                SET precio = ?, icono = ?, disponible = ?, stock = ?, categoria_id = ?
                WHERE nombre = ?
            """, (precio, icono, int(disponible), stock, cat_id, nombre))
    else:
        # Inserción de nuevo producto
        if not foto_ruta:
            FOTO_DEFECTO = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"
            foto_ruta = FOTO_DEFECTO
            
        cursor.execute("""
            INSERT INTO productos (nombre, precio, icono, disponible, foto, stock, categoria_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (nombre, precio, icono, int(disponible), foto_ruta, stock, cat_id))
        
    conn.commit()
    conn.close()

def eliminar_producto(db_path, nombre):
    """Elimina un producto por su nombre y borra su archivo de imagen local si no es default."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT foto FROM productos WHERE nombre = ?", (nombre,))
    row = cursor.fetchone()
    if row:
        foto_ruta = row[0]
        # Borrar el archivo de imagen si es un archivo físico en disco
        if foto_ruta and not foto_ruta.startswith("data:"):
            ruta_a_borrar = foto_ruta
            if not os.path.exists(ruta_a_borrar) and not os.path.isabs(foto_ruta):
                dir_db = os.path.dirname(db_path)
                if dir_db:
                    ruta_a_borrar = os.path.join(dir_db, foto_ruta)
            
            if os.path.exists(ruta_a_borrar):
                try:
                    os.remove(ruta_a_borrar)
                except Exception as e:
                    print(f"Error borrando archivo de imagen {ruta_a_borrar}: {e}")
                
    cursor.execute("DELETE FROM productos WHERE nombre = ?", (nombre,))
    conn.commit()
    conn.close()

def obtener_ordenes(db_path):
    """Retorna el historial completo de boletas/órdenes."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total FROM ordenes ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    
    ordenes = []
    for r in rows:
        ordenes.append({
            "Fecha y Hora": r[0],
            "Nro. Boleta": r[1],
            "Detalle Artículos": r[2],
            "Entrega": r[3],
            "Método Pago": r[4],
            "Total": r[5]
        })
    return ordenes

def crear_orden(db_path, fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total):
    """Inserta una nueva orden en el historial."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ordenes (fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fecha_hora, nro_boleta, detalle_articulos, entrega, metodo_pago, total))
    conn.commit()
    conn.close()

def actualizar_stock(db_path, nombre, stock_restante):
    """Actualiza el stock de un producto específico."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE productos SET stock = ? WHERE nombre = ?", (stock_restante, nombre))
    conn.commit()
    conn.close()
