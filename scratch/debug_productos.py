import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import database

try:
    # Configurar output a utf-8 para evitar errores de emojis
    sys.stdout.reconfigure(encoding='utf-8')
    menu = database.obtener_menu()
    first_item = list(menu.keys())[0]
    print(f"Producto: '{first_item}'")
    print("Keys del diccionario del producto:", list(menu[first_item].keys()))
    
    clean_dict = {}
    for k, v in menu[first_item].items():
        if k == 'foto':
            clean_dict[k] = f"{str(v)[:30]}... (len: {len(str(v))})"
        else:
            clean_dict[k] = str(v)
            
    print("Contenido:", clean_dict)
except Exception as e:
    print("Error:", e)
