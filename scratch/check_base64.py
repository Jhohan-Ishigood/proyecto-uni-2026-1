import os
import sys
import base64
from PIL import Image
from io import BytesIO

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import database

try:
    conn = database.get_connection()
    df = conn.read(worksheet="productos", ttl=1)
    print("\n--- VALIDACIÓN DE BASE64 DE IMÁGENES ---")
    for idx, row in df.iterrows():
        nombre = row.get('nombre')
        foto = str(row.get('foto') or '').strip()
        
        if not foto:
            print(f"Producto: '{nombre}' | Sin foto")
            continue
            
        if foto.startswith("data:image/"):
            try:
                # Extraer la parte de datos del base64
                header, data = foto.split(",", 1)
                img_bytes = base64.b64decode(data)
                img = Image.open(BytesIO(img_bytes))
                print(f"Producto: '{nombre}' | Base64 VÁLIDO | Formato: {img.format} | Tamaño: {img.size}")
            except Exception as e:
                print(f"Producto: '{nombre}' | Base64 CORRUPTO/INVÁLIDO | Error: {e}")
        else:
            print(f"Producto: '{nombre}' | No es Base64 (comienza con: '{foto[:20]}')")
except Exception as e:
    print("Error:", e)
