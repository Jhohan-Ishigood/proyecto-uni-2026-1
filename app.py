# ============================================================================
# 1. CONFIGURACIÓN DEL SISTEMA, IMPORTACIONES Y RUTAS DE CONTROL
# ============================================================================
import streamlit as st
from datetime import datetime, timedelta, timezone
import os
import base64
import html as html_lib
from PIL import Image
from io import BytesIO
import pandas as pd
import altair as alt
import streamlit.components.v1 as components
import re
import unicodedata
from urllib.parse import quote
import urllib.parse
import importlib
import database
importlib.reload(database)
import requests

# Configuración inicial del lienzo responsivo de la aplicación
st.set_page_config(
    page_title="Carnes & Bytes - Sistema de Pedidos", 
    page_icon="🥩", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

st.markdown('<meta name="description" content="Carnes & Bytes - Sistema de pedidos online. Parrillas, hamburguesas y más. Delivery disponible.">', unsafe_allow_html=True)

# Determinación dinámica y automática de la ruta raíz en servidores de producción
BASE_DIR = ""
OPCIONES_CARPETA = [
    "El Gran Buffalo-Python", "El Gran Búfalo-Python", 
    "El Gran Bufalo-Python", "El Gran Búfalo-Pitón"
]
for carpeta in OPCIONES_CARPETA:
    if os.path.exists(carpeta):
        BASE_DIR = f"{carpeta}/"
        break

# Mapeo unificado de archivos físicos
RUTA_CSS = os.path.join(BASE_DIR, "estilos.css")
RUTA_HTML = os.path.join(BASE_DIR, "boleta_plantilla.html")
URL_BANNER_LOCAL = os.path.join(BASE_DIR, "Captura de pantalla 2026-05-24 090610.png")
WHATSAPP_NEGOCIO = "51982174847"
HORA_APERTURA = 8
HORA_CIERRE = 23

MIN_SEGUNDOS_ENTRE_BOLETAS = 10  # Rate limiting: mínimo de segundos entre emisiones

# Inicialización de la conexión a Google Sheets (base de datos en la nube)
database.inicializar_db()

# ============================================================================
# 1.5 GOOGLE OAUTH CONFIGURATION
# ============================================================================
GOOGLE_CLIENT_ID = "370627253754-bbk3sri9i6ou057ikrbpt72j9rhfo7qv.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "")
if not GOOGLE_CLIENT_SECRET and "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
    GOOGLE_CLIENT_SECRET = st.secrets["connections"]["gsheets"].get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "https://proyecto-uni-2026-1.streamlit.app/"

def get_google_auth_url():
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    return f"{auth_url}?{urllib.parse.urlencode(params)}"

@st.dialog("¡Oferta Exclusiva! 🎁", width="small")
def mostrar_promo_login():
    st.markdown("#### ¡Inicia sesión ahora mismo!")
    st.write("Obtén un **15% de descuento** en tu primera compra y empieza a sumar puntos para ganar increíbles premios.")
    st.markdown("<br>", unsafe_allow_html=True)
    auth_url = get_google_auth_url()
    st.markdown(f'<a href="{auth_url}" target="_blank" style="display:inline-block; width:100%; text-align:center; background-color:#f39c12; padding:12px 0; border-radius:8px; text-decoration:none;"><span style="color:#000000 !important; font-weight:bold; font-size:16px;">Continúa con Google</span></a>', unsafe_allow_html=True)

def get_google_token(code):
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    res = requests.post(token_url, data=data)
    if res.status_code == 200:
        return res.json()
    return {"error_status": res.status_code, "error_response": res.text}

def get_google_user_info(access_token):
    user_info_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    headers = {"Authorization": f"Bearer {access_token}"}
    res = requests.get(user_info_url, headers=headers)
    if res.status_code == 200:
        return res.json()
    return None

# ============================================================================
# 2. FUNCIONES AUXILIARES PARA MANEJO DE IMÁGENES Y STRINGS
# ============================================================================

def sanitizar_nombre(texto):
    """Sanitiza el nombre del producto para usarlo como nombre de archivo."""
    texto = texto.lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = re.sub(r'[^a-z0-9_]', '_', texto)
    texto = re.sub(r'_+', '_', texto)
    return texto.strip('_')

def escapar_html(valor):
    """Escapa texto dinámico antes de insertarlo en HTML renderizado por Streamlit."""
    return html_lib.escape(str(valor), quote=True)

def generar_numero_boleta(historial_ordenes):
    """Calcula el siguiente correlativo desde el mayor número de boleta existente."""
    mayor = 0
    for orden in historial_ordenes:
        nro_boleta = str(orden.get("Nro. Boleta", ""))
        match = re.search(r"(\d+)$", nro_boleta)
        if match:
            mayor = max(mayor, int(match.group(1)))
    return mayor + 1

def validar_carrito_con_stock(carrito):
    """Relee el menú sin caché y confirma que el carrito todavía tenga stock suficiente.
    Si la lectura fresca falla (API quota), usa el menú cacheado como fallback."""
    menu_actualizado = database.obtener_menu()

    # Fallback: si la lectura fresca retornó vacío pero hay un menú cacheado,
    # usar el caché en lugar de marcar todo como "no existe".
    if not menu_actualizado and st.session_state.get("menu_dinamico"):
        menu_actualizado = st.session_state.menu_dinamico

    errores = []
    carrito_limpio = []

    for item in carrito:
        producto = item["producto"]
        cantidad = int(item["cantidad"])
        info = menu_actualizado.get(producto)

        if not info:
            errores.append(f"'{producto}' fue eliminado de la carta y se quitó del carrito.")
            continue

        stock_actual = int(info.get("stock", 0))
        if not info.get("disponible", False):
            errores.append(f"'{producto}' ya no está disponible y se quitó del carrito.")
            continue

        if stock_actual < cantidad:
            if stock_actual > 0:
                # Ajustar cantidad al stock real
                item["cantidad"] = stock_actual
                item["subtotal"] = stock_actual * float(info["precio"])
                errores.append(f"'{producto}' solo tiene {stock_actual} unidad(es). Se ajustó la cantidad.")
                carrito_limpio.append(item)
            else:
                errores.append(f"'{producto}' se agotó y se quitó del carrito.")
        else:
            carrito_limpio.append(item)

    # Actualizar el carrito en session_state con los items válidos
    if len(carrito_limpio) != len(carrito):
        st.session_state.carrito = carrito_limpio
        st.session_state.total_acumulado = sum(i["subtotal"] for i in carrito_limpio)

    return len(errores) == 0, menu_actualizado, errores

def pedidos_abiertos(ahora):
    """Valida horario operativo local y pausa manual de pedidos."""
    return HORA_APERTURA <= ahora.hour < HORA_CIERRE and not st.session_state.get("pedidos_pausados", False)

def tiempo_estimado_texto(tiene_delivery=False):
    return "30-45 min" if tiene_delivery else "15-20 min"

def normalizar_telefono(texto):
    return re.sub(r"\D+", "", texto or "")

def calcular_descuento(codigo, subtotal, costo_delivery, total_items):
    codigo_normalizado = (codigo or "").strip().upper()
    if not codigo_normalizado:
        return 0.0, ""

    cupones_db = database.obtener_cupones(ttl=database.TTL_LECTURA)
    cupon = cupones_db.get(codigo_normalizado)
    if not cupon:
        return 0.0, "Código de cupón no válido."
    
    if not cupon.get("activo", True):
        return 0.0, "Este cupón ya no está activo."

    if codigo_normalizado == "COMBO5" and total_items < 3:
        return 0.0, "COMBO5 requiere al menos 3 productos."

    if cupon["tipo"] == "porcentaje":
        descuento = subtotal * cupon["valor"]
    elif cupon["tipo"] == "delivery":
        descuento = min(costo_delivery, cupon["valor"])
    else:
        descuento = min(subtotal + costo_delivery, cupon["valor"])

    return round(descuento, 2), f"{codigo_normalizado}: {cupon['descripcion']}"

def recalcular_carrito(carrito):
    total = 0.0
    carrito_limpio = []
    for item in carrito:
        producto = item["producto"]
        cantidad = int(item["cantidad"])
        if cantidad <= 0 or producto not in st.session_state.menu_dinamico:
            continue
        precio = float(st.session_state.menu_dinamico[producto]["precio"])
        subtotal = precio * cantidad
        carrito_limpio.append({"producto": producto, "cantidad": cantidad, "subtotal": subtotal})
        total += subtotal
    return carrito_limpio, total

def construir_mensaje_whatsapp(correlativo, carrito, total, entrega, cliente, telefono):
    lineas = [
        "Hola, Carnes & Bytes.",
        f"Pedido {correlativo}:",
    ]
    for item in carrito:
        lineas.append(f"- {item['cantidad']}x {item['producto']} = S/{item['subtotal']:.2f}")
    lineas.extend([
        f"Entrega: {entrega}",
        f"Cliente: {cliente or 'No indicado'}",
        f"Telefono: {telefono or 'No indicado'}",
        f"Total: S/{total:.2f}",
    ])
    return f"https://wa.me/{WHATSAPP_NEGOCIO}?text={quote(chr(10).join(lineas))}"

def render_stepper(paso_actual):
    """Renderiza un stepper visual de progreso para el flujo del cliente."""
    pasos = [("🛒", "Selección"), ("💳", "Pago"), ("✅", "Listo")]
    html = "<div style='display:flex; justify-content:center; align-items:center; gap:0; margin:10px 0 20px 0;'>"
    for i, (icono, nombre) in enumerate(pasos):
        activo = i < paso_actual
        actual = i == paso_actual - 1
        color = '#f39c12' if activo else '#666'
        bg = 'rgba(243,156,18,0.15)' if actual else 'transparent'
        border = '2px solid #f39c12' if actual else '2px solid #444'
        html += "<div style='display:flex;align-items:center;'>"
        html += f"<div style='width:32px;height:32px;border-radius:50%;background:{bg};border:{border};display:flex;align-items:center;justify-content:center;font-size:14px;'>{icono}</div>"
        html += f"<span style='margin-left:6px;color:{color};font-weight:700;font-size:12px;'>{nombre}</span>"
        if i < len(pasos) - 1:
            line_color = '#f39c12' if activo else '#444'
            html += f"<div style='width:30px;height:2px;background:{line_color};margin:0 6px;'></div>"
        html += "</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

def convertir_imagen_a_base64(archivo_foto, max_dimension=400, calidad=70):
    """Convierte y comprime una imagen subida a un Data URL Base64 optimizado para Google Sheets (máx 50,000 chars por celda)."""
    if archivo_foto is None:
        return None
    try:
        img = Image.open(archivo_foto)
        # Convertir a RGB si tiene canal alfa (PNG con transparencia)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Redimensionar manteniendo proporción
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        # Comprimir como JPEG
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=calidad, optimize=True)
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        st.error(f"Error al codificar la imagen a Base64: {e}")
        return None

@st.cache_data(show_spinner=False)
def obtener_src_foto(ruta_foto):
    """Convierte una ruta de imagen local a Base64 o la retorna tal cual si es una data URL. Almacenada en caché para extrema velocidad."""
    if not ruta_foto:
        return "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"
    
    if ruta_foto.startswith("data:image/"):
        return ruta_foto
        
    if os.path.exists(ruta_foto):
        ruta_completa = ruta_foto
    else:
        ruta_completa = os.path.join(BASE_DIR, ruta_foto) if not os.path.isabs(ruta_foto) else ruta_foto
    
    if os.path.exists(ruta_completa):
        try:
            _, ext = os.path.splitext(ruta_completa)
            ext = ext.lower().replace(".", "")
            if ext == "jpg":
                ext = "jpeg"
            with open(ruta_completa, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            return f"data:image/{ext};base64,{encoded}"
        except Exception as e:
            print(f"Error codificando imagen {ruta_completa}: {e}")
            
    return "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"

def _get_perm(rol, seccion):
    """Devuelve el nivel de permiso: 'oculto', 'ver', o 'editar'."""
    if rol == "Dueño":
        return "editar"
    raw = st.session_state.get("permisos_roles", {}).get(rol, {}).get(seccion, "oculto")
    # compatibilidad con formato bool antiguo
    if isinstance(raw, bool):
        return "ver" if raw else "oculto"
    return raw

def puede_ver(rol, seccion):
    """True si el rol puede ver la sección (nivel 'ver' o 'editar')."""
    return _get_perm(rol, seccion) in ("ver", "editar")

def puede_editar(rol, seccion):
    """True si el rol puede editar/modificar la sección (nivel 'editar')."""
    return _get_perm(rol, seccion) == "editar"

# ============================================================================
# 3. INICIALIZACIÓN DE VARIABLES REACTIVAS DE SESIÓN (ESTADOS DEL SISTEMA)
# ============================================================================
# Carga inicial de datos (solo una vez por sesión, o cuando se fuerza recarga)
if "menu_dinamico" not in st.session_state or st.session_state.get("_forzar_recarga", False):
    if st.session_state.get("_forzar_recarga", False):
        st.cache_data.clear() # Limpiar caché local de Streamlit para traer datos frescos de GSheets
    
    nuevo_menu = database.obtener_menu()
    cant_productos = len(nuevo_menu)
    if nuevo_menu:
        st.session_state.menu_dinamico = nuevo_menu
        if cant_productos < 5 and st.session_state.get("mostrar_diagnostico", True):
            st.info(f"📊 Diagnóstico: {cant_productos} productos cargados desde Google Sheets. "
                    f"Si esperas más, verifica que la hoja 'productos' tenga todos los datos "
                    f"y que la columna 'nombre' contenga los nombres de cada producto.")
    elif "menu_dinamico" not in st.session_state:
        st.session_state.menu_dinamico = {}

    nuevas_ordenes = database.obtener_ordenes()
    if nuevas_ordenes:
        st.session_state.historial_ordenes = nuevas_ordenes
    elif "historial_ordenes" not in st.session_state:
        st.session_state.historial_ordenes = []

    nuevas_categorias = database.obtener_categorias()
    if nuevas_categorias:
        st.session_state.lista_categorias = ["Todos"] + nuevas_categorias
    elif "lista_categorias" not in st.session_state:
        st.session_state.lista_categorias = ["Todos"]
    
    st.session_state["_forzar_recarga"] = False

    st.session_state.carrito = []
if "total_acumulado" not in st.session_state:
    st.session_state.total_acumulado = 0.0
if "pedido_guardado" not in st.session_state:
    st.session_state.pedido_guardado = False
if "boleta_emitida" not in st.session_state:
    st.session_state.boleta_emitida = False
if "pantalla_actual" not in st.session_state:
    st.session_state.pantalla_actual = "bienvenida"
if "solo_navegar" not in st.session_state:
    st.session_state.solo_navegar = False
if "tipo_servicio" not in st.session_state:
    st.session_state.tipo_servicio = "salon" # "salon" | "delivery" | "navegar"
if "direccion_cliente" not in st.session_state:
    st.session_state.direccion_cliente = ""
if "nombre_cliente" not in st.session_state:
    st.session_state.nombre_cliente = ""
if "categoria_activa" not in st.session_state:
    st.session_state.categoria_activa = "Todos"
if "pedidos_pausados" not in st.session_state:
    st.session_state.pedidos_pausados = False
if "cliente_nombre" not in st.session_state:
    st.session_state.cliente_nombre = ""
if "cliente_telefono" not in st.session_state:
    st.session_state.cliente_telefono = ""
if "cupon_aplicado" not in st.session_state:
    st.session_state.cupon_aplicado = ""
if "favoritos" not in st.session_state:
    st.session_state.favoritos = set()
if "ultima_boleta_time" not in st.session_state:
    st.session_state.ultima_boleta_time = 0
if "mesa_seleccionada" not in st.session_state:
    st.session_state.mesa_seleccionada = None
if "correlativo_sunat" not in st.session_state:
    st.session_state.correlativo_sunat = ""
if "mostrar_login_reserva" not in st.session_state:
    st.session_state.mostrar_login_reserva = False


# Permisos configurables por el Dueño — 3 niveles: "oculto" | "ver" | "editar"
if "permisos_roles_v2" not in st.session_state:
    st.session_state.permisos_roles = {
        "Cocinero": {
            "bitacora":       "ver",
            "mesas_reservas": "ver",
            "cupones":        "oculto",
            "finanzas":       "oculto",
            "carta":          "oculto",
        },
        "Cajero": {
            "bitacora":       "ver",
            "mesas_reservas": "ver",
            "cupones":        "editar",
            "finanzas":       "ver",
            "carta":          "oculto",
        },
        "Mesero": {
            "bitacora":       "ver",
            "mesas_reservas": "editar",
            "cupones":        "oculto",
            "finanzas":       "oculto",
            "carta":          "oculto",
        },
    }
    st.session_state.permisos_roles_v2 = True  # marca migración completada

# Inicialización segura de variables del session_state al arranque
if "lista_categorias" not in st.session_state:
    st.session_state.lista_categorias = ["Todos"]
if "categoria_activa" not in st.session_state:
    st.session_state.categoria_activa = "Todos"

# Defensa contra categorías activas eliminadas
if st.session_state.categoria_activa not in st.session_state.lista_categorias:
    st.session_state.categoria_activa = "Todos"

if "user_info" not in st.session_state:
    st.session_state.user_info = None

# ============================================================================
# 3.5 MANEJO DE CALLBACK OAUTH (GOOGLE LOGIN)
# ============================================================================
if "code" in st.query_params:
    code = st.query_params["code"]
    st.query_params.clear() # Limpiar la URL para seguridad y estética
    token_data = get_google_token(code)
    
    if token_data and "access_token" in token_data:
        user_info = get_google_user_info(token_data["access_token"])
        if user_info:
            st.session_state.user_info = user_info
            st.session_state.db_user = None
            email = user_info.get("email")
            nombre = user_info.get("name")
            foto = user_info.get("picture")
            
            db_user = database.obtener_usuario(email)
            if not db_user:
                cupon = database.registrar_usuario(email, nombre, foto)
                if cupon:
                    st.toast(f"¡Te regalamos 15% Dcto! Tu cupón: {cupon}", icon="🎉")
            else:
                st.toast(f"¡Hola de nuevo, {nombre}!", icon="👋")
        else:
            st.error("Error al obtener el perfil de usuario de Google.")
    else:
        st.error(f"Error al intercambiar el token con Google. Verifica que el Client Secret en Streamlit Cloud sea correcto. Respuesta: {token_data}")

# Anclaje y sincronización de reloj oficial para Perú (GMT-5)
zona_peru = timezone(timedelta(hours=-5))
ahora_peru = datetime.now(zona_peru)
fecha_actual = ahora_peru.strftime("%d/%m/%Y %H:%M:%S")
servicio_abierto = True

# ============================================================================
# 4. MOTOR DE ANALÍTICA COMERCIAL Y PROCESAMIENTO DE KPI'S
# ============================================================================
total_caja = 0.0
total_pedidos = len(st.session_state.historial_ordenes)

# Estructuras limpias para contabilidad y conteo de inventario vendido
conteos_productos = {prod: 0 for prod in st.session_state.menu_dinamico.keys()}
metodos_pagos = {"Efectivo": 0.0, "Yape": 0.0, "Tarjeta": 0.0}

# Procesamiento del historial de transacciones en la base de datos JSON
for orden in st.session_state.historial_ordenes:
    try:
        total_str = str(orden.get("Total", "0")).replace("S/", "").strip()
        monto_num = float(total_str) if total_str and total_str != "nan" else 0.0
        total_caja += monto_num
        
        if orden["Método Pago"] in metodos_pagos:
            metodos_pagos[orden["Método Pago"]] += monto_num
            
        detalle = orden["Detalle Artículos"]
        partes = detalle.split(", ")
        for parte in partes:
            for prod in conteos_productos.keys():
                if f"x {prod}" in parte or parte.endswith(prod):
                    try:
                        cant_txt = parte.split("x")[0].strip()
                        conteos_productos[prod] += int(cant_txt)
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass  # Evita que una orden corrupta detenga el software

# Generación del número correlativo automático para la siguiente boleta
st.session_state.numero_boleta = generar_numero_boleta(st.session_state.historial_ordenes)
# ============================================================================
def load_css():
    with open(RUTA_CSS, "r", encoding="utf-8") as f:
        return f.read()

if os.path.exists(RUTA_CSS):
    st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)

# Inyección limpia del sello de creador adaptado al flujo estructural
st.markdown("<div class='sello-creador'>Pagina elaborada por el grupo 5 😎</div>", unsafe_allow_html=True)

if "promo_mostrada" not in st.session_state:
    st.session_state.promo_mostrada = True
    if "user_info" not in st.session_state or not st.session_state.user_info:
        mostrar_promo_login()

# ============================================================================
# HEADER GLOBAL: PERFIL DE USUARIO EN PARTE SUPERIOR (MOBILE FRIENDLY)
# ============================================================================
with st.container():
    if st.session_state.user_info:
        u_info = st.session_state.user_info
        if "db_user" not in st.session_state or st.session_state.db_user is None:
            st.session_state.db_user = database.obtener_usuario(u_info.get('email', ''))
        db_user = st.session_state.db_user
        compras = int(float(db_user.get("compras_realizadas", 0))) if db_user else 0
        faltan = int(3 - (compras % 3))
        primer_nombre = u_info.get('name', '').split(' ')[0]
        foto_url = u_info.get('picture', '')
        email = u_info.get('email', '')
        
        # CSS para posicionar la pastilla de perfil arriba a la derecha y corregir el despliegue del menú
        st.markdown(f"""
        <style>
        /* Deshabilitar pointer-events en el header para que no bloquee clics */
        div[data-testid="stHeader"] {{
            pointer-events: none !important;
        }}
        
        /* ===== PASTILLA DE PERFIL: FIJA ARRIBA A LA DERECHA ===== */
        div[data-testid="stPopover"] {{
            position: fixed !important;
            top: 60px !important; /* Debajo de la barra de Streamlit Cloud */
            right: 20px !important;
            left: auto !important;
            transform: none !important;
            margin: 0 !important;
            z-index: 999999 !important;
            width: auto !important;
            pointer-events: auto !important;
        }}
        /* Botón con la foto circular recortada y borde dorado */
        div[data-testid="stPopover"] button {{
            background-color: rgba(12, 12, 12, 0.9) !important;
            border: 1.5px solid rgba(243, 156, 18, 0.8) !important;
            border-radius: 50px !important;
            backdrop-filter: blur(12px) !important;
            padding: 6px 16px 6px 44px !important; /* Espacio para la foto circular */
            min-height: 42px !important;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5) !important;
            transition: all 0.25s ease !important;
            position: relative !important;
            width: auto !important;
            display: inline-flex !important;
            align-items: center !important;
            pointer-events: auto !important;
        }}
        /* Pseudo-elemento para recortar la foto de perfil en círculo perfecto */
        div[data-testid="stPopover"] button::before {{
            content: "" !important;
            display: block !important;
            position: absolute !important;
            left: 6px !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            width: 30px !important;
            height: 30px !important;
            border-radius: 50% !important;
            border: 1.5px solid #f39c12 !important;
            background-image: url('{foto_url}') !important;
            background-size: cover !important;
            background-position: center !important;
            pointer-events: none !important; /* Evita interferir con los clics */
        }}
        div[data-testid="stPopover"] button:hover {{
            background-color: rgba(243, 156, 18, 0.2) !important;
            border-color: #f39c12 !important;
            box-shadow: 0 6px 20px rgba(243, 156, 18, 0.3) !important;
        }}
        /* Texto del botón */
        div[data-testid="stPopover"] button p {{
            margin: 0 !important;
            font-size: 13px !important;
            font-weight: 700 !important;
            color: #fff !important;
            display: flex !important;
            align-items: center !important;
            gap: 4px !important;
        }}
        /* Panel desplegable premium */
        div[data-testid="stPopoverBody"] {{
            background: rgba(12, 12, 12, 0.96) !important;
            backdrop-filter: blur(20px) !important;
            border: 1px solid rgba(243, 156, 18, 0.3) !important;
            border-radius: 16px !important;
            box-shadow: 0 20px 60px rgba(0,0,0,0.8) !important;
            min-width: 285px !important;
            z-index: 1000000 !important;
        }}
        /* Botones del menú desplegable */
        div[data-testid="stPopoverBody"] button {{
            background: transparent !important;
            border: none !important;
            border-bottom: 1px solid rgba(255,255,255,0.06) !important;
            border-radius: 0 !important;
            color: #ddd !important;
            padding: 14px 20px !important;
            text-align: left !important;
            justify-content: flex-start !important;
            transition: background 0.2s !important;
            width: 100% !important;
            display: flex !important;
        }}
        div[data-testid="stPopoverBody"] button:hover {{
            background: rgba(243, 156, 18, 0.12) !important;
            color: #f39c12 !important;
        }}
        div[data-testid="stPopoverBody"] button p {{
            font-size: 14px !important;
            font-weight: 500 !important;
        }}
        /* Celular */
        @media (max-width: 768px) {{
            div[data-testid="stPopover"] {{
                top: 60px !important; /* Mantener abajo también en celular */
                right: 10px !important;
            }}
            div[data-testid="stPopover"] button {{
                padding: 5px 12px 5px 38px !important;
                min-height: 38px !important;
            }}
            div[data-testid="stPopover"] button::before {{
                width: 26px !important;
                height: 26px !important;
                left: 5px !important;
            }}
            div[data-testid="stPopoverBody"] {{
                min-width: 250px !important;
            }}
        }}
        </style>
        """, unsafe_allow_html=True)

        with st.popover(f"{primer_nombre}"):
            # --- Cabecera del menú: foto + info ---
            st.markdown(
                f"<div style='padding: 20px 18px 15px; border-bottom: 1px solid rgba(255,255,255,0.08); display: flex; align-items: center; gap: 14px;'>"
                f"<img src='{foto_url}' style='border-radius:50%; width:50px; height:50px; object-fit:cover; border: 2px solid #f39c12; flex-shrink:0;'>"
                f"<div style='line-height:1.3;'>"
                f"<span style='font-size:16px; font-weight:800; color:#fff;'>Hola, {primer_nombre}</span><br>"
                f"<span style='font-size:11px; color:#888;'>{email}</span><br>"
                f"<span style='font-size:11px; color:#f39c12; font-weight:600;'>🏆 {compras} compras realizadas</span>"
                f"</div></div>",
                unsafe_allow_html=True
            )
            
            # --- Barra de progreso hacia descuento ---
            progreso = (compras % 3) / 3
            st.markdown(
                f"<div style='padding: 10px 18px 12px;'>"
                f"<span style='font-size:11px; color:#aaa;'>Próximo descuento en {faltan} compra{'s' if faltan > 1 else ''}</span>"
                f"<div style='background: rgba(255,255,255,0.08); border-radius: 10px; height: 6px; margin-top: 5px; overflow: hidden;'>"
                f"<div style='background: linear-gradient(90deg, #f39c12, #e67e22); height: 100%; width: {progreso*100}%; border-radius: 10px; transition: width 0.5s;'></div>"
                f"</div></div>",
                unsafe_allow_html=True
            )
            
            st.markdown("<div style='padding: 0;'>", unsafe_allow_html=True)
            
            # --- Opciones del menú ---
            if st.button("📋  Mis Pedidos", use_container_width=True, key="btn_pop_pedidos"):
                st.session_state.pantalla_actual = "mis_pedidos"
                st.rerun()
                
            if st.button("🍽️  Ver Menú", use_container_width=True, key="btn_pop_menu"):
                st.session_state.pantalla_actual = "catalogo"
                st.rerun()
            
            if st.button("📅  Hacer Reserva", use_container_width=True, key="btn_pop_reserva"):
                st.session_state.pantalla_actual = "reservas"
                st.rerun()
            
            if st.button("📌  Mis Reservas", use_container_width=True, key="btn_pop_mis_reservas"):
                st.session_state.pantalla_actual = "mis_reservas"
                st.rerun()
                
            if st.button("⭐  Programa de Fidelidad", use_container_width=True, key="btn_pop_fidelidad"):
                st.toast(f"🏆 Llevas {compras} compras. ¡Cada 3 compras obtienes descuento!", icon="⭐")
            
            if st.button("💬  Soporte WhatsApp", use_container_width=True, key="btn_pop_soporte"):
                st.markdown("<meta http-equiv='refresh' content='0;url=https://wa.me/51982174847'>", unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # --- Botón salir (rojo) ---
            st.markdown("<div style='padding: 5px 0; border-top: 1px solid rgba(255,255,255,0.08);'>", unsafe_allow_html=True)
            if st.button("🚪  Cerrar Sesión", use_container_width=True, key="btn_pop_logout"):
                st.session_state.user_info = None
                st.session_state.db_user = None
                if st.session_state.pantalla_actual == "mis_pedidos":
                    st.session_state.pantalla_actual = "bienvenida"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        auth_url = get_google_auth_url()
        st.markdown(
            f"<div class='status-strip' style='border-color: #f39c12; justify-content: space-between !important; padding: 15px 20px !important; margin-top: 5px !important; max-width: 100% !important;'>"
            f"<div style='font-size:14px; font-weight:bold; color:#fff; line-height:1.4; text-align: left;'>"
            f"🎁 ¡Inicia sesión y obtén<br><span style='color:#f39c12; font-size:14px !important;'>15% Dcto en tu 1era compra!</span>"
            f"</div>"
            f"<a href='{auth_url}' target='_blank' style='display:inline-block; background-color:#f39c12; padding:10px 18px; border-radius:8px; text-decoration:none; white-space:nowrap;'>"
            f"<span style='color:#000000 !important; font-weight:bold; font-size:14px;'>Iniciar Sesión</span>"
            f"</a>"
            f"</div>",
            unsafe_allow_html=True
        )
        st.markdown("<hr style='margin-top:10px; margin-bottom:15px; border-color:#333;'>", unsafe_allow_html=True)

# ============================================================================
# 6. BARRA LATERAL (SIDEBAR POS): GESTIÓN INTERNA Y AUTENTICACIÓN
# ============================================================================
st.sidebar.markdown("<h2 style='text-align: center; color: #f39c12;'>🥩 Carnes & Bytes</h2>", unsafe_allow_html=True)
st.sidebar.markdown("<p style='text-align: center; font-size: 13px; color: #aaa;'>Especialistas en carnes y parrillas premium al carbón de manera artesanal.</p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

# Control del estado visual del formulario de inicio de sesión
if "mostrar_login_admin" not in st.session_state:
    st.session_state.mostrar_login_admin = False

st.sidebar.markdown("#### ⚙️ GESTIÓN INTERNA")
if st.sidebar.button("INGRESAR COMO ADMINISTRADOR🤵‍♂️", use_container_width=True, key="btn_toggle_admin_login"):
    st.session_state.mostrar_login_admin = not st.session_state.mostrar_login_admin

# Inicialización limpia de variables de control de acceso
usuario_input = ""
clave_input = ""
es_admin = False

if st.session_state.mostrar_login_admin:
    with st.sidebar.container():
        usuario_input = st.text_input("Nombre de Usuario:", key="user_login").strip()
        clave_input = st.text_input("Contraseña:", type="password", key="pass_login").strip()

# Validación de credenciales blindada: sin secrets configurados no hay acceso admin
USER_PROD = st.secrets.get("admin_user", "Grupo 5")
PASS_PROD = st.secrets.get("admin_password", "jhohan-2026")
credenciales_admin_configuradas = bool(USER_PROD and PASS_PROD)

es_admin_autenticado = credenciales_admin_configuradas and usuario_input == USER_PROD and clave_input == PASS_PROD

# Retroalimentación interactiva en barra lateral
if es_admin_autenticado:
    st.sidebar.success("✔ Autenticación exitosa")
    # Inicializamos rol en la primera autenticación si no está fijado
    if "rol_actual" not in st.session_state or st.session_state.rol_actual is None:
        st.session_state.rol_actual = None
elif st.session_state.mostrar_login_admin and not credenciales_admin_configuradas:
    st.sidebar.warning("Admin no configurado. Agregue admin_user and admin_password en Streamlit Secrets.")
elif usuario_input or clave_input:
    st.sidebar.error("❌ Credenciales incorrectas")

# Determinamos si se ha seleccionado un rol para entrar al Panel Administrativo
es_admin = es_admin_autenticado and st.session_state.get("rol_actual") is not None

st.sidebar.markdown("---")
st.sidebar.markdown("#### 🕒 HORARIO DE ATENCIÓN")
st.sidebar.caption("Lunes a Domingo: 8:00 AM - 11:00 PM")

st.sidebar.markdown("#### 📍 NUESTRA UBICACIÓN")
st.sidebar.caption("Av. Principal Carnes & Bytes 742, Trujillo, Perú")
st.sidebar.markdown("---")

st.sidebar.markdown("#### 📞 ¿NECESITAS AYUDA?")

# Enlace de soporte por WhatsApp optimizado
st.sidebar.link_button(
    "💬 Chatear con Soporte",
    "https://wa.me",
    use_container_width=True,
    key="link_whatsapp_soporte"
)
# ============================================================================
# 7. BARRA DE EXPLORACIÓN GLOBAL MAESTRA (ESTILO NETFLIX MINIMALISTA)
# ============================================================================

# Inicialización de la variable de búsqueda limpia por defecto
busqueda = ""

# Renderizado condicional de la barra horizontal
if es_admin or (st.session_state.pantalla_actual == "catalogo" and not st.session_state.pedido_guardado):
    st.markdown("<div class='netflix-navbar-master'>", unsafe_allow_html=True)
    
    # Grid de dos columnas asimétricas estables para separar pestañas y buscador
    col_izq_tabs, col_der_search = st.columns([4.0, 1.0], gap="small")
    
    with col_izq_tabs:
        # Selector horizontal premium unificado indexado dinámicamente
        categoria_seleccionada = st.radio(
            "Categorías Navegación MASTER",
            options=st.session_state.lista_categorias,
            index=st.session_state.lista_categorias.index(st.session_state.categoria_activa),
            horizontal=True,
            label_visibility="collapsed",
            key="tabs_netflix_master_final_key"
        )
        
        # SOLUCIONADO: Sincronización limpia instantánea al cambiar de pestaña
        if categoria_seleccionada != st.session_state.categoria_activa:
            st.session_state.categoria_activa = categoria_seleccionada
            st.rerun()
            
    with col_der_search:
        placeholder_txt = "Buscar..." if es_admin else "¿Qué buscas?"
        
        # Captura de datos para filtros precisos sin alterar estados globales
        busqueda = st.text_input(
            "🔍 Buscar", 
            placeholder=placeholder_txt, 
            label_visibility="collapsed", 
            key="search_bar_master_final_key"
        ).strip().lower()
        
    st.markdown("</div><br>", unsafe_allow_html=True)

# ============================================================================
# 7.5 PANTALLA DE SELECCIÓN DE ROL VISUAL (PREMIUM CARD SELECTOR)
# ============================================================================
if es_admin_autenticado and st.session_state.rol_actual is None:
    st.markdown("<h2 style='text-align:center; color:#f39c12; margin-top:20px;'>🔑 ACCESO AUTORIZADO</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center; color:#aaa; margin-bottom: 25px;'>Por favor, seleccione su rol operativo para ingresar al sistema:</p>", unsafe_allow_html=True)

    # Inicialización de metadatos de roles si no existen
    if "roles_metadata" not in st.session_state:
        st.session_state.roles_metadata = {
            "Dueño": {"icon": "👑", "desc": "Acceso total y administración de permisos de todo el sistema."},
            "Cocinero": {"icon": "🍳", "desc": "Visualiza la bitácora de pedidos pendientes y estado de mesas."},
            "Cajero": {"icon": "💰", "desc": "Control financiero, cupones de descuento, caja chica y reservas."},
            "Mesero": {"icon": "🚶", "desc": "Registro de comandas, bitácora básica de pedidos y mesas del salón."}
        }

    # Generamos la lista de roles combinando 'Dueño' + llaves de st.session_state.permisos_roles
    roles_sistema = ["Dueño"] + list(st.session_state.permisos_roles.keys())
    
    # Creamos las columnas responsivamente según la cantidad de roles del sistema
    n_cols = len(roles_sistema)
    cols_lista = st.columns(n_cols, gap="medium") if n_cols > 0 else []

    for idx, r_nombre in enumerate(roles_sistema):
        meta = st.session_state.roles_metadata.get(r_nombre, {"icon": "👤", "desc": "Rol operativo personalizado con permisos definidos por el Dueño."})
        with cols_lista[idx]:
            with st.container(border=True):
                st.markdown(f"""
                <div style='text-align:center; margin-bottom:15px;'>
                    <span style='font-size:48px; display:block; margin-bottom:10px;'>{meta['icon']}</span>
                    <h3 style='margin:5px 0; color:#f39c12; font-size:22px; font-weight:bold; letter-spacing:0.5px;'>{r_nombre}</h3>
                    <p style='font-size:12px; color:#888; margin:10px 0 0 0; line-height:1.4; min-height:60px;'>{meta['desc']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"Entrar como {r_nombre}", key=f"btn_choose_role_{r_nombre}", use_container_width=True, type="primary"):
                    st.session_state.rol_actual = r_nombre
                    st.rerun()

    st.markdown("<br><br>", unsafe_allow_html=True)
    col_logout_btn, _ = st.columns([1.5, 3])
    with col_logout_btn:
        if st.button("🚪 Cerrar Sesión Administrativa", use_container_width=True, key="btn_admin_logout_main"):
            # Limpiar credenciales
            st.session_state.mostrar_login_admin = False
            st.session_state.rol_actual = None
            st.rerun()

# ============================================================================
# 8. PANEL DE CONTROL DE ADMINISTRACIÓN - GESTOR DE SECCIONES (JSON)
# ============================================================================
if es_admin:
    rol_actual = st.session_state.get("rol_actual", "Dueño")
    
    # --- SISTEMA DE ALERTA DE NUEVOS PEDIDOS Y LLAMADOS DE MESA ---
    # Inicializar estado para registrar conteo de órdenes
    if "total_ordenes_previo" not in st.session_state:
        st.session_state.total_ordenes_previo = len(st.session_state.get("historial_ordenes", []))
        
    conteo_ordenes_actual = len(st.session_state.get("historial_ordenes", []))
    sonido_alerta = False
    
    # 1. Alerta por nuevas órdenes registradas
    if conteo_ordenes_actual > st.session_state.total_ordenes_previo:
        st.session_state.total_ordenes_previo = conteo_ordenes_actual
        sonido_alerta = True
        st.toast("🔥 ¡NUEVO PEDIDO RECIBIDO EN COCINA! 🔥", icon="🔔")

    # 2. Alerta por llamados activos de clientes en mesa
    alertas_activas = database.obtener_alertas(ttl=2)
    if "conteo_alertas_previo" not in st.session_state:
        st.session_state.conteo_alertas_previo = len(alertas_activas)
        
    if len(alertas_activas) > st.session_state.conteo_alertas_previo:
        st.session_state.conteo_alertas_previo = len(alertas_activas)
        sonido_alerta = True
        st.toast("🚨 ¡NUEVO LLAMADO DE CLIENTE EN MESA! 🚨", icon="🙋‍♂️")
    elif len(alertas_activas) < st.session_state.conteo_alertas_previo:
        st.session_state.conteo_alertas_previo = len(alertas_activas)

    # Inyección de audio HTML para campana (ding) de cocina real si se activa una alerta
    if sonido_alerta:
        # Sonido clásico de campana
        audio_src = "https://assets.mixkit.co/active_storage/sfx/2869/2869-84.wav"
        st.markdown(f'<audio src="{audio_src}" autoplay style="display:none;"></audio>', unsafe_allow_html=True)

    # Cabecera con título y botones de control de sesión/rol
    col_admin_t, col_admin_b1, col_admin_b2, col_admin_b3 = st.columns([2.0, 1.0, 1.0, 1.2])
    with col_admin_t:
        st.markdown(f"<h1 class='titulo-principal' style='text-align:left; margin:0; padding:0;'>📊 PANEL ({rol_actual.upper()})</h1>", unsafe_allow_html=True)
    with col_admin_b1:
        if st.button("🔄 Cambiar de Rol", use_container_width=True, key="btn_admin_change_role_header"):
            st.session_state.rol_actual = None
            st.rerun()
    with col_admin_b2:
        if st.button("🚪 Salir de Admin", use_container_width=True, key="btn_admin_logout_header"):
            st.session_state.mostrar_login_admin = False
            st.session_state.rol_actual = None
            st.rerun()

            
    st.info(f"📋 **Reporte Gerencial del Grupo 5** — Sincronizado en tiempo real: {fecha_actual}")

    # Panel visual de Llamadas de Mesa activas (para roles con permiso de bitácora)
    if puede_ver(rol_actual, "bitacora") and alertas_activas:
        st.markdown("### 🚨 LLAMADAS DE CLIENTES EN ESPERA")
        with st.container(border=True):
            for alert in alertas_activas:
                col_al_info, col_al_btn = st.columns([4, 1])
                with col_al_info:
                    emoji_tipo = "🙋‍♂️" if alert["tipo_alerta"] == "Llamado a Mesero" else "💵"
                    st.markdown(f"**{emoji_tipo} {alert['tipo_alerta'].upper()}** — Mesa **{int(float(alert['nro_mesa']))}** ({alert['cliente_nombre']})")
                    st.caption(f"Enviado a las {alert['fecha_hora']}")
                with col_al_btn:
                    if st.button("✅ Atendido", key=f"btn_atender_{alert['nro_mesa']}_{alert['tipo_alerta']}", use_container_width=True):
                        database.atender_alerta_salon(alert['nro_mesa'], alert['tipo_alerta'])
                        st.toast("Llamado marcado como atendido", icon="✅")
                        st.rerun()
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔕 Silenciar / Actualizar todo", use_container_width=True, key="btn_refresh_alerts"):
                st.rerun()
    
    if puede_ver(rol_actual, "carta"):
        st.session_state.pedidos_pausados = st.toggle(
            "Pausar recepción de pedidos de clientes",
            value=st.session_state.pedidos_pausados,
            help="Bloquea temporalmente nuevos pedidos sin modificar la carta.",
        )
        if st.session_state.pedidos_pausados:
            st.warning("La recepción de pedidos está pausada para esta sesión.")
        st.markdown("<br>", unsafe_allow_html=True)

    # ============================================================
    # PANEL DE PERMISOS DE ROLES (solo visible al Dueño)
    # ============================================================
    if rol_actual == "Dueño":
        with st.expander("🔐 GESTIÓN DE PERMISOS POR ROL", expanded=False):
            st.caption("Configura para cada rol si puede **ver**, **editar**, u **ocultar** cada sección.")
            st.markdown("""
<div style='background:#1a1a2e; border:1px solid #333; border-radius:8px; padding:10px 16px; margin-bottom:12px; font-size:13px;'>
🔴 <b>Oculto</b> — No aparece en su panel &nbsp;|&nbsp;
👁️ <b>Solo Ver</b> — Lo ve pero no puede modificar nada &nbsp;|&nbsp;
✏️ <b>Editar</b> — Acceso completo para modificar
</div>
""", unsafe_allow_html=True)

            LABELS_SECCIONES = {
                "carta":          ("📝", "Carta (precios, stock, productos)"),
                "cupones":        ("🎫", "Cupones de descuento"),
                "finanzas":       ("📊", "Auditoría de caja / Analítica"),
                "bitacora":       ("🕒", "Bitácora de pedidos"),
                "mesas_reservas": ("🪑", "Mesas y reservaciones"),
            }
            # Cargar dinámicamente los roles editables desde session_state.permisos_roles
            ROLES_EDITABLES = list(st.session_state.permisos_roles.keys())
            OPCIONES = ["oculto", "ver", "editar"]
            OPCIONES_LABELS = {"oculto": "🔴 Oculto", "ver": "👁️ Solo Ver", "editar": "✏️ Editar"}

            permisos_tmp = {}
            # Cabecera de tabla
            header_cols = st.columns([1.5] + [1] * len(LABELS_SECCIONES))
            with header_cols[0]:
                st.markdown("**Rol**")
            for idx, (clave, (icono, etiqueta)) in enumerate(LABELS_SECCIONES.items()):
                with header_cols[idx + 1]:
                    st.markdown(f"**{icono} {etiqueta}**")

            st.markdown("---")

            for rol_e in ROLES_EDITABLES:
                permisos_tmp[rol_e] = {}
                row_cols = st.columns([1.5] + [1] * len(LABELS_SECCIONES))
                with row_cols[0]:
                    meta_r = st.session_state.roles_metadata.get(rol_e, {"icon": "👤", "desc": ""})
                    st.markdown(f"**{meta_r['icon']} {rol_e}**")
                for idx, (clave, _) in enumerate(LABELS_SECCIONES.items()):
                    with row_cols[idx + 1]:
                        actual = st.session_state.permisos_roles.get(rol_e, {}).get(clave, "oculto")
                        if isinstance(actual, bool):
                            actual = "ver" if actual else "oculto"
                        sel = st.selectbox(
                            "nivel",
                            options=OPCIONES,
                            index=OPCIONES.index(actual) if actual in OPCIONES else 0,
                            format_func=lambda x: OPCIONES_LABELS[x],
                            key=f"perm_{rol_e}_{clave}",
                            label_visibility="collapsed"
                        )
                        permisos_tmp[rol_e][clave] = sel
                st.markdown("")

            if st.button("💾 GUARDAR PERMISOS", use_container_width=True, key="btn_guardar_permisos"):
                # Actualizar los permisos en el estado
                st.session_state.permisos_roles = permisos_tmp
                st.session_state.permisos_roles_v2 = True
                st.success("✔ ¡Permisos actualizados correctamente!")
                st.rerun()

            st.markdown("<br><hr><br>", unsafe_allow_html=True)
            st.markdown("#### 🔧 GESTIONAR LISTA DE ROLES")
            
            col_add_rol, col_del_rol = st.columns(2, gap="medium")
            
            with col_add_rol:
                with st.container(border=True):
                    st.markdown("##### ➕ Añadir Nuevo Rol")
                    nuevo_rol_nombre = st.text_input("Nombre del Rol:", placeholder="Ej: Supervisor, Practicante...").strip().capitalize()
                    col_icon, col_desc = st.columns([1, 4])
                    with col_icon:
                        nuevo_rol_icon = st.text_input("Icono (Emoji):", value="👤", max_chars=2)
                    with col_desc:
                        nuevo_rol_desc = st.text_input("Descripción breve:", placeholder="Ej: Asistencia y control de personal...")
                    
                    if st.button("➕ CREAR ROL", use_container_width=True, key="btn_crear_rol_nuevo"):
                        if not nuevo_rol_nombre:
                            st.error("Por favor, ingresa un nombre para el nuevo rol.")
                        elif nuevo_rol_nombre in st.session_state.permisos_roles or nuevo_rol_nombre == "Dueño":
                            st.error("El rol ya existe.")
                        else:
                            # Inicializar permisos por defecto para el rol creado
                            st.session_state.permisos_roles[nuevo_rol_nombre] = {
                                "carta": "oculto",
                                "cupones": "oculto",
                                "finanzas": "oculto",
                                "bitacora": "oculto",
                                "mesas_reservas": "oculto"
                            }
                            # Guardar metadatos de visualización (icono/desc)
                            st.session_state.roles_metadata[nuevo_rol_nombre] = {
                                "icon": nuevo_rol_icon.strip() or "👤",
                                "desc": nuevo_rol_desc.strip() or "Rol operativo personalizado con permisos definidos por el Dueño."
                            }
                            st.success(f"Rol '{nuevo_rol_nombre}' creado con éxito.")
                            st.rerun()

            with col_del_rol:
                with st.container(border=True):
                    st.markdown("##### 🗑️ Quitar Rol Existente")
                    roles_borrables = [r for r in ROLES_EDITABLES]
                    rol_a_borrar = st.selectbox("Seleccione el rol a eliminar:", options=roles_borrables, key="select_rol_a_borrar")
                    
                    st.warning("⚠️ Al eliminar un rol, se perderán de inmediato todas sus configuraciones de permisos.")
                    if st.button("🗑️ ELIMINAR ROL SELECCIONADO", use_container_width=True, key="btn_eliminar_rol_existente", type="primary"):
                        if rol_a_borrar in st.session_state.permisos_roles:
                            del st.session_state.permisos_roles[rol_a_borrar]
                            if rol_a_borrar in st.session_state.roles_metadata:
                                del st.session_state.roles_metadata[rol_a_borrar]
                            st.success(f"Rol '{rol_a_borrar}' eliminado exitosamente.")
                            st.rerun()

    # Bloque expandible de control de pestañas y categorías
    if puede_ver(rol_actual, "carta"):
        with st.expander("📁 ⚙️ CONFIGURACIÓN DE SECCIONES EN LA CARTA", expanded=False):
            st.caption("Añada nuevas pestañas al menú horizontal o elimine las secciones que ya no utilice en la jornada.")
            if not puede_editar(rol_actual, "carta"):
                st.info("👁️ Modo solo lectura — no tienes permiso para modificar las secciones.")
            st.markdown("<br>", unsafe_allow_html=True)
    
            _editar_carta = puede_editar(rol_actual, "carta")
            col_cat1, col_cat2 = st.columns(2, gap="medium")
            
            with col_cat1:
                with st.container(border=True):
                    st.markdown("##### ➕ Crear Nueva Sección")
                    nueva_cat = st.text_input(
                        "Crear Sección", 
                        placeholder="Escribe aquí la nueva sección (Ej. Postres)...", 
                        key="input_create_cat_name",
                        label_visibility="collapsed",
                        disabled=not _editar_carta
                    ).strip().capitalize()
                    
                    if st.button("➕ CREAR NUEVA SECCIÓN", use_container_width=True, key="btn_create_cat", disabled=not _editar_carta):
                        if nueva_cat and nueva_cat != "Todos":
                            exito = database.crear_categoria(None, nueva_cat)
                            if exito:
                                st.success(f"✔ ¡Sección '{nueva_cat}' integrada con éxito!")
                                st.session_state["_forzar_recarga"] = True
                                st.rerun()
                            else:
                                st.error("⚠️ Error: Esta categoría ya existe en el menú.")
                        elif nueva_cat == "Todos":
                            st.error("⚠️ Error: 'Todos' es una sección reservada.")
                        else:
                            st.error("⚠️ Error: El nombre no puede estar vacío.")
                        
            with col_cat2:
                with st.container(border=True):
                    st.markdown("##### 🗑️ Eliminar Sección Seleccionada")
                    cats_borrables = [c for c in st.session_state.lista_categorias if c != "Todos"]
                    
                    cat_a_borrar = st.selectbox(
                        "Eliminar Sección", 
                        options=cats_borrables, 
                        key="select_delete_cat_name",
                        label_visibility="collapsed",
                        disabled=not _editar_carta
                    )
                    
                    if st.button("🗑️ ELIMINAR SECCIÓN SELECCIONADA", use_container_width=True, key="btn_delete_cat", disabled=not _editar_carta):
                        if cat_a_borrar:
                            database.eliminar_categoria(None, cat_a_borrar)
                            if st.session_state.categoria_activa == cat_a_borrar:
                                st.session_state.categoria_activa = "Todos"
                                
                            st.warning(f"🗑️ Sección '{cat_a_borrar}' removida físicamente de la carta.")
                            st.session_state["_forzar_recarga"] = True
                            st.rerun()
    # ============================================================================
    # 9. PANEL DE CONTROL DE ADMINISTRACIÓN - INSERCIÓN DE PRODUCTOS MULTIMEDIA
    # ============================================================================
    if puede_ver(rol_actual, "carta"):
        with st.expander("➕ 🛠️ AÑADIR NUEVO PRODUCTO CON FOTO", expanded=False):
            st.caption("Complete los datos para agregar un plato nuevo subiendo una imagen desde su dispositivo.")
            _editar_carta2 = puede_editar(rol_actual, "carta")
            if not _editar_carta2:
                st.info("👁️ Modo solo lectura — no tienes permiso para agregar productos.")
            nuevo_nombre = st.text_input("Nombre del nuevo producto:", placeholder="Ej. Alitas BBQ, Papas Nativas...", disabled=not _editar_carta2).strip()
            
            col_new1, col_new2, col_new3, col_new4 = st.columns(4)
            with col_new1:
                nuevo_precio = st.number_input("Precio de venta (S/):", min_value=0.5, value=10.0, step=0.5, disabled=not _editar_carta2)
            with col_new2:
                nuevo_icono = st.text_input("Icono (Emoji):", value="🍟", max_chars=2, disabled=not _editar_carta2).strip()
            with col_new3:
                nuevo_stock = st.number_input("Stock (Unidades):", min_value=0, value=15, step=1, disabled=not _editar_carta2)
            with col_new4:
                cats_creadas = [c for c in st.session_state.lista_categorias if c != "Todos"]
                nueva_categoria_asociada = st.selectbox("Categoría asignada:", options=cats_creadas, disabled=not _editar_carta2)
                
            archivo_foto = st.file_uploader("Selecciona la foto del plato desde tu equipo:", type=["jpg", "jpeg", "png"], key="upload_nuevo_prod", disabled=not _editar_carta2)
                
            if st.button("🚀 GUARDAR E INTEGRAR NUEVO PRODUCTO", use_container_width=True, disabled=not _editar_carta2):
                if nuevo_nombre:
                    if nuevo_nombre not in st.session_state.menu_dinamico:
                        ruta_foto = convertir_imagen_a_base64(archivo_foto)
    
                        exito_guardado = database.guardar_producto(
                            db_path=None,
                            nombre=nuevo_nombre,
                            precio=nuevo_precio,
                            icono=nuevo_icono,
                            disponible=True,
                            foto_ruta=ruta_foto,
                            stock=int(nuevo_stock),
                            categoria_nombre=nueva_categoria_asociada
                        )
                        if exito_guardado:
                            st.success(f"✔ ¡{nuevo_icono} {nuevo_nombre} integrado con éxito en '{nueva_categoria_asociada}'!")
                            st.session_state["_forzar_recarga"] = True
                            st.rerun()
                    else:
                        st.error("⚠️ Error: Ese producto ya existe en la carta actual.")
                else:
                    st.error("⚠️ Error: El nombre del producto no puede estar vacío.")

    # ============================================================================
    # 10. PANEL DE CONTROL DE ADMINISTRACIÓN - FILTRADO INTELIGENTE DE PRODUCTOS
    # ============================================================================
    if puede_ver(rol_actual, "carta"):
        _editar_carta3 = puede_editar(rol_actual, "carta")
        st.markdown("### 📝 GESTIÓN DE PRECIOS, STOCK Y FOTOS")
        st.caption(f"Modifique los valores. Filtrado actual: **{st.session_state.categoria_activa}**")
        if not _editar_carta3:
            st.info("👁️ Modo solo lectura — puedes ver los productos pero no modificarlos.")
        
        eliminar_producto = None
        productos_lista = list(st.session_state.menu_dinamico.keys())
        productos_filtrados_admin = []
        
        for prod in productos_lista:
            if busqueda and busqueda not in prod.lower():
                continue
                
            info_prod = st.session_state.menu_dinamico[prod]
            cat_prod = info_prod.get("categoria", "Parrillas")
            
            if st.session_state.categoria_activa == "Todos" or st.session_state.categoria_activa == cat_prod:
                productos_filtrados_admin.append(prod)
    
        # Alertas de stock bajo
        productos_stock_bajo = [p for p, info in st.session_state.menu_dinamico.items() if info.get('stock', 0) <= 3 and info.get('stock', 0) > 0]
        productos_agotados = [p for p, info in st.session_state.menu_dinamico.items() if info.get('stock', 0) == 0]
        if productos_stock_bajo:
            st.warning(f"⚠️ Stock bajo ({len(productos_stock_bajo)}): {', '.join(productos_stock_bajo)}")
        if productos_agotados:
            st.error(f"🚫 Agotados ({len(productos_agotados)}): {', '.join(productos_agotados)}")
    
        # ============================================================================
        # 11. PANEL DE CONTROL DE ADMINISTRACIÓN - BUCLE DE EDICIÓN RESPONSIVO INDEPENDIENTE
        # ============================================================================
        # Inicializamos un diccionario temporal para capturar cambios sin destruir la reactividad en caliente
        cambios_detectados = {}
    
        for i in range(0, len(productos_filtrados_admin), 2):
            col_ed1, col_ed2 = st.columns(2, gap="medium")
            
            # --- CONTROL DE PRODUCTO: COLUMNA IZQUIERDA ---
            p_izq = productos_filtrados_admin[i]
            with col_ed1:
                with st.container(border=True):
                    st.markdown(f"### {st.session_state.menu_dinamico[p_izq]['icono']} {p_izq}")
                    foto_actual_izq = st.session_state.menu_dinamico[p_izq].get("foto", "")
                    
                    # Cargar preview (de disco, Base64 o la subida actualmente en session_state)
                    foto_preview_izq = obtener_src_foto(foto_actual_izq)
                    if f"f_up_{p_izq}" in st.session_state and st.session_state[f"f_up_{p_izq}"] is not None:
                        try:
                            bytes_f = st.session_state[f"f_up_{p_izq}"].getvalue()
                            encoded_f = base64.b64encode(bytes_f).decode()
                            foto_preview_izq = f"data:image/png;base64,{encoded_f}"
                        except Exception:
                            pass
                            
                    if foto_preview_izq:
                        st.markdown(f"""<img src="{foto_preview_izq}" style="width:100%; height:120px; object-fit:cover; border-radius:6px; margin-bottom:10px; border: 1px solid #444;">""", unsafe_allow_html=True)
                    
                    # Selector dinámico de secciones para reasignar categorías en caliente
                    cats_izq = [c for c in st.session_state.lista_categorias if c != "Todos"]
                    cat_act_izq = st.session_state.menu_dinamico[p_izq].get("categoria", "Parrillas")
                    if cat_act_izq not in cats_izq and cats_izq: 
                        cats_izq.append(cat_act_izq)
                    
                    nueva_cat_izq = st.selectbox(f"Sección de {p_izq}:", options=cats_izq, index=cats_izq.index(cat_act_izq) if cat_act_izq in cats_izq else 0, key=f"cat_edit_{p_izq}", disabled=not _editar_carta3)
                    
                    p_izq_val = st.number_input(f"Precio (S/) - {p_izq}:", min_value=1.0, value=float(st.session_state.menu_dinamico[p_izq]["precio"]), step=0.5, key=f"p_{p_izq}", disabled=not _editar_carta3)
                    p_izq_disp = st.checkbox("Disponible para venta", value=st.session_state.menu_dinamico[p_izq]["disponible"], key=f"d_{p_izq}", disabled=not _editar_carta3)
                    p_izq_stock = st.number_input(f"Stock Disponible - {p_izq}:", min_value=0, value=int(st.session_state.menu_dinamico[p_izq].get("stock", 10)), step=1, key=f"s_{p_izq}", disabled=not _editar_carta3)
                    
                    foto_cambio_izq = st.file_uploader(f"Actualizar foto de {p_izq}:", type=["jpg", "jpeg", "png"], key=f"f_up_{p_izq}", disabled=not _editar_carta3)
                    
                    cambios_detectados[p_izq] = {
                        "precio": p_izq_val, 
                        "icono": st.session_state.menu_dinamico[p_izq]["icono"], 
                        "disponible": p_izq_disp, 
                        "stock": p_izq_stock, 
                        "categoria": nueva_cat_izq
                    }
                    
                    if _editar_carta3:
                        if st.button(f"❌ Eliminar {p_izq}", key=f"del_{p_izq}", use_container_width=True):
                            eliminar_producto = p_izq
                    else:
                        st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                        if p_izq_stock > 0 and p_izq_disp:
                            st.markdown(f"<div style='background-color:rgba(39,174,96,0.15); border:1px solid #27ae60; color:#2cc76b; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;'>🟢 En Stock ({p_izq_stock} uds)</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='background-color:rgba(231,76,60,0.15); border:1px solid #e74c3c; color:#ff6b6b; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;'>🔴 Agotado / No Disponible</div>", unsafe_allow_html=True)
                    
            # --- CONTROL DE PRODUCTO: COLUMNA DERECHA ---
            if i + 1 < len(productos_filtrados_admin):
                p_der = productos_filtrados_admin[i+1]
                with col_ed2:
                    with st.container(border=True):
                        st.markdown(f"### {st.session_state.menu_dinamico[p_der]['icono']} {p_der}")
                        foto_actual_der = st.session_state.menu_dinamico[p_der].get("foto", "")
                        
                        # Cargar preview (de disco, Base64 o la subida actualmente en session_state)
                        foto_preview_der = obtener_src_foto(foto_actual_der)
                        if f"f_up_{p_der}" in st.session_state and st.session_state[f"f_up_{p_der}"] is not None:
                            try:
                                bytes_f = st.session_state[f"f_up_{p_der}"].getvalue()
                                encoded_f = base64.b64encode(bytes_f).decode()
                                foto_preview_der = f"data:image/png;base64,{encoded_f}"
                            except Exception:
                                pass
                                
                        if foto_preview_der:
                            st.markdown(f"""<img src="{foto_preview_der}" style="width:100%; height:120px; object-fit:cover; border-radius:6px; margin-bottom:10px; border: 1px solid #444;">""", unsafe_allow_html=True)
                        
                        # Selector dinámico de secciones para la columna derecha
                        cats_der = [c for c in st.session_state.lista_categorias if c != "Todos"]
                        cat_act_der = st.session_state.menu_dinamico[p_der].get("categoria", "Parrillas")
                        if cat_act_der not in cats_der and cats_der: 
                            cats_der.append(cat_act_der)
                        
                        nueva_cat_der = st.selectbox(f"Sección de {p_der}:", options=cats_der, index=cats_der.index(cat_act_der) if cat_act_der in cats_der else 0, key=f"cat_edit_{p_der}", disabled=not _editar_carta3)
                        
                        p_der_val = st.number_input(f"Precio (S/) - {p_der}:", min_value=1.0, value=float(st.session_state.menu_dinamico[p_der]["precio"]), step=0.5, key=f"p_{p_der}", disabled=not _editar_carta3)
                        p_der_disp = st.checkbox("Disponible para venta", value=st.session_state.menu_dinamico[p_der]["disponible"], key=f"d_{p_der}", disabled=not _editar_carta3)
                        p_der_stock = st.number_input(f"Stock Disponible - {p_der}:", min_value=0, value=int(st.session_state.menu_dinamico[p_der].get("stock", 10)), step=1, key=f"s_{p_der}", disabled=not _editar_carta3)
                        
                        foto_cambio_der = st.file_uploader(f"Actualizar foto de {p_der}:", type=["jpg", "jpeg", "png"], key=f"f_up_{p_der}", disabled=not _editar_carta3)
                        
                        cambios_detectados[p_der] = {
                            "precio": p_der_val, 
                            "icono": st.session_state.menu_dinamico[p_der]["icono"], 
                            "disponible": p_der_disp, 
                            "stock": p_der_stock, 
                            "categoria": nueva_cat_der
                        }
                        
                        if _editar_carta3:
                            if st.button(f"❌ Eliminar {p_der}", key=f"del_{p_der}", use_container_width=True):
                                eliminar_producto = p_der
                        else:
                            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                            if p_der_stock > 0 and p_der_disp:
                                st.markdown(f"<div style='background-color:rgba(39,174,96,0.15); border:1px solid #27ae60; color:#2cc76b; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;'>🟢 En Stock ({p_der_stock} uds)</div>", unsafe_allow_html=True)
                            else:
                                st.markdown("<div style='background-color:rgba(231,76,60,0.15); border:1px solid #e74c3c; color:#ff6b6b; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;'>🔴 Agotado / No Disponible</div>", unsafe_allow_html=True)
            st.markdown("---")
    
        # ============================================================================
        # 12. MANEJADOR OPERATIVO DE PERSISTENCIA SEGURA
        # ============================================================================
        if eliminar_producto is not None:
            if database.eliminar_producto(None, eliminar_producto):
                st.success(f"✔ ¡Producto '{eliminar_producto}' eliminado con éxito!")
                st.session_state["_forzar_recarga"] = True
                st.rerun()
    
        if st.button("💾 CONFIRMAR Y SINCRONIZAR CAMBIOS DE LA CARTA", use_container_width=True, disabled=not _editar_carta3):
            # Sincronizamos los cambios al almacenamiento de Google Sheets
            try:
                todos_guardados = True
                for prod_key, info_actualizada in cambios_detectados.items():
                    archivo_subido = st.session_state.get(f"f_up_{prod_key}")
                    ruta_foto = convertir_imagen_a_base64(archivo_subido)
                        
                    todos_guardados = database.guardar_producto(
                        db_path=None,
                        nombre=prod_key,
                        precio=info_actualizada["precio"],
                        icono=info_actualizada["icono"],
                        disponible=info_actualizada["disponible"],
                        foto_ruta=ruta_foto,
                        stock=info_actualizada["stock"],
                        categoria_nombre=info_actualizada["categoria"]
                    ) and todos_guardados
                if todos_guardados:
                    st.success("✔ ¡Cambios guardados físicamente con éxito!")
                    st.session_state["_forzar_recarga"] = True
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar en Google Sheets: {e}. Por favor, vuelve a intentarlo en un momento.")

    # ============================================================================
    # 12.5 PANEL DE CONTROL DE ADMINISTRACIÓN - GESTIÓN DE CUPONES
    # ============================================================================
    if puede_ver(rol_actual, "cupones"):
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🎫 GESTIÓN DE CUPONES")
        _editar_cup = puede_editar(rol_actual, "cupones")
        if not _editar_cup:
            st.info("👁️ Modo solo lectura — puedes ver los cupones pero no agregarlos ni eliminarlos.")
        
        with st.expander("Añadir / Editar Cupones", expanded=False):
            c_col1, c_col2, c_col3, c_col4 = st.columns(4)
            with c_col1:
                nuevo_codigo = st.text_input("Código del cupón (ej. VERANO20)", disabled=not _editar_cup).strip().upper()
            with c_col2:
                nuevo_tipo = st.selectbox("Tipo de descuento", ["porcentaje", "monto", "delivery"], disabled=not _editar_cup)
            with c_col3:
                nuevo_valor = st.number_input("Valor (ej. 0.2 para 20%, o 10.0 para S/10)", min_value=0.0, step=0.1, disabled=not _editar_cup)
            with c_col4:
                nueva_desc = st.text_input("Descripción breve", disabled=not _editar_cup)
                
            if st.button("➕ Guardar Cupón", use_container_width=True, disabled=not _editar_cup):
                if nuevo_codigo and nuevo_valor > 0:
                    if database.crear_cupon(nuevo_codigo, nuevo_tipo, nuevo_valor, nueva_desc, activo=True):
                        st.success(f"Cupón {nuevo_codigo} guardado.")
                        st.rerun()
                else:
                    st.error("Ingrese código y valor mayor a 0.")
                    
            st.markdown("#### Cupones Actuales")
            cupones_db = database.obtener_cupones(ttl=database.TTL_LECTURA)
            if cupones_db:
                for cod, datos in cupones_db.items():
                    col_c1, col_c2, col_c3, col_c4 = st.columns([2, 3, 1, 1])
                    with col_c1:
                        st.markdown(f"**{cod}**")
                        st.caption(f"{datos['tipo']} - {datos['valor']}")
                    with col_c2:
                        st.write(datos["descripcion"])
                    with col_c3:
                        estado = st.toggle("Activo", value=bool(datos["activo"]), key=f"tgl_{cod}", disabled=not _editar_cup)
                        if _editar_cup and estado != bool(datos["activo"]):
                            database.actualizar_estado_cupon(cod, estado)
                            st.rerun()
                    with col_c4:
                        if st.button("🗑️", key=f"del_cup_{cod}", disabled=not _editar_cup):
                            database.eliminar_cupon(cod)
                            st.rerun()
            else:
                st.info("No hay cupones registrados.")

    # ============================================================================
    # 13. PANEL DE CONTROL DE ADMINISTRACIÓN - AUDITORÍA FINANCIERA Y ANALÍTICA
    # ============================================================================
    if puede_ver(rol_actual, "finanzas"):
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 📊 AUDITORÍA GENERAL DE CAJA CHICA")
    
        col_kpi1, col_kpi2 = st.columns(2)
        with col_kpi1:
            st.markdown(f"<div style='background-color: #151515; padding: 20px; border-radius: 8px; border-left: 5px solid #27ae60; box-shadow: 0px 4px 10px rgba(0,0,0,0.3);'><p style='margin:0; font-size:14px; color:#aaa; font-weight:bold;'>💰 RECAUDACIÓN TOTAL ACUMULADA</p><h2 style='margin:5px 0 0 0; color:#fff; font-size:32px;'>S/{total_caja:.2f}</h2></div>", unsafe_allow_html=True)
        with col_kpi2:
            st.markdown(f"<div style='background-color: #151515; padding: 20px; border-radius: 8px; border-left: 5px solid #f39c12; box-shadow: 0px 4px 10px rgba(0,0,0,0.3);'><p style='margin:0; font-size:14px; color:#aaa; font-weight:bold;'>📦 ÓRDENES HISTÓRICAS PROCESADAS</p><h2 style='margin:5px 0 0 0; color:#fff; font-size:32px;'>{total_pedidos} Pedidos</h2></div>", unsafe_allow_html=True)
    
        col_kpi3, col_kpi4 = st.columns(2)
        ticket_promedio = total_caja / total_pedidos if total_pedidos > 0 else 0
        with col_kpi3:
            st.markdown(f"<div style='background-color:#151515;padding:20px;border-radius:8px;border-left:5px solid #d35400;box-shadow:0px 4px 10px rgba(0,0,0,0.3);'><p style='margin:0;font-size:14px;color:#aaa;font-weight:bold;'>🎯 TICKET PROMEDIO</p><h2 style='margin:5px 0 0 0;color:#fff;font-size:32px;'>S/{ticket_promedio:.2f}</h2></div>", unsafe_allow_html=True)
        
        # Hora pico
        horas_pedidos: dict = {}
        for orden in st.session_state.historial_ordenes:
            try:
                hora = orden.get('Fecha y Hora', '').split(' ')[1].split(':')[0]
                horas_pedidos[hora] = horas_pedidos.get(hora, 0) + 1
            except (IndexError, KeyError):
                pass
        hora_pico = max(horas_pedidos, key=lambda k: horas_pedidos[k]) if horas_pedidos else "--"
        with col_kpi4:
            st.markdown(f"<div style='background-color:#151515;padding:20px;border-radius:8px;border-left:5px solid #3498db;box-shadow:0px 4px 10px rgba(0,0,0,0.3);'><p style='margin:0;font-size:14px;color:#aaa;font-weight:bold;'>⏰ HORA PICO</p><h2 style='margin:5px 0 0 0;color:#fff;font-size:32px;'>{hora_pico}:00 hrs</h2></div>", unsafe_allow_html=True)
    
        fecha_reporte = st.date_input("Filtrar reporte por fecha", value=ahora_peru.date(), key="fecha_reporte_admin")
        ordenes_fecha = []
        for orden in st.session_state.historial_ordenes:
            try:
                fecha_orden = datetime.strptime(orden.get("Fecha y Hora", "")[:10], "%d/%m/%Y").date()
                if fecha_orden == fecha_reporte:
                    ordenes_fecha.append(orden)
            except ValueError:
                continue
    
        ventas_fecha = 0.0
        for orden in ordenes_fecha:
            try:
                ventas_fecha += float(orden["Total"].replace("S/", "").strip())
            except (ValueError, KeyError):
                pass
        ticket_fecha = ventas_fecha / len(ordenes_fecha) if ordenes_fecha else 0.0
    
        col_dia1, col_dia2, col_dia3 = st.columns(3)
        col_dia1.metric("Ventas del día", f"S/{ventas_fecha:.2f}")
        col_dia2.metric("Pedidos del día", len(ordenes_fecha))
        col_dia3.metric("Ticket promedio día", f"S/{ticket_fecha:.2f}")
            
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 📈 ANALÍTICA: UNIDADES VENDIDAS DE LA JORNADA")
        
        df_grafico = pd.DataFrame({
            'Producto': list(conteos_productos.keys()),
            'Cantidad': list(conteos_productos.values())
        })
        
        barras = alt.Chart(df_grafico).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
            x=alt.X('Producto:N', title='Productos del Menú', sort=None, axis=alt.Axis(
                labelAngle=-90,           # Inclina los nombres en diagonal para que entren todos
                labelOverlap=False,       # OBLIGATORIO: Fuerza a Altair a mostrar el 100% de nombres
                labelColor='#ffffff',     
                titleColor='#f39c12', 
                labelFontSize=11
            )),
            y=alt.Y('Cantidad:Q', title='Unidades Vendidas', axis=alt.Axis(
                grid=True, 
                gridColor='#2c2c2c', 
                labelColor='#ffffff', 
                titleColor='#f39c12'
            )),
            color=alt.Color('Cantidad:Q', scale=alt.Scale(scheme='orangered'), legend=None)
        )
        
        texto_etiquetas = barras.mark_text(align='center', baseline='bottom', dy=-5, color='#ffffff', fontSize=13, fontWeight='bold').encode(text='Cantidad:Q')
        grafico_final = (barras + texto_etiquetas).properties(width=600, height=320).configure_view(strokeWidth=0).configure_axis(domainWidth=1, domainColor='#444444')
        st.altair_chart(grafico_final, use_container_width=True)
        
        # Tendencia por horas
        st.markdown("### 📈 TENDENCIA DE VENTAS POR HORA")
        horas_pedidos = {}
        for orden in st.session_state.historial_ordenes:
            try:
                # Buscar llave "Fecha y Hora" o la equivalente en keys
                llave_fecha = "Fecha y Hora" if "Fecha y Hora" in orden else list(orden.keys())[0]
                hora = orden[llave_fecha].split(" ")[1].split(":")[0]
                horas_pedidos[hora] = horas_pedidos.get(hora, 0) + 1
            except Exception:
                pass
        if horas_pedidos:
            df_horas = pd.DataFrame(list(horas_pedidos.items()), columns=['Hora', 'Pedidos']).sort_values('Hora')
            line_chart = alt.Chart(df_horas).mark_line(point=True, color='#f39c12', strokeWidth=3).encode(
                x=alt.X('Hora:N', title='Hora del Día'),
                y=alt.Y('Pedidos:Q', title='Cantidad de Pedidos')
            ).properties(height=250)
            st.altair_chart(line_chart, use_container_width=True)

    # ============================================================================
    # 14. PANEL DE CONTROL DE ADMINISTRACIÓN - BITÁCORA HISTÓRICA DE PEDIDOS
    # ============================================================================
    if puede_ver(rol_actual, "bitacora"):
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🕒 BITÁCORA: CONTROL HISTÓRICO DE PEDIDOS")
        if st.session_state.historial_ordenes:
            df_historial = pd.DataFrame(st.session_state.historial_ordenes)
            csv_data = df_historial.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 EXPORTAR HISTORIAL A CSV",
                data=csv_data,
                file_name=f"historial_{fecha_actual.split(' ')[0].replace('/','-')}.csv",
                mime="text/csv",
                use_container_width=True,
                key="btn_export_historial"
            )
            # Renombrar columnas de forma segura usando un diccionario de mapeo
            df_historial = df_historial.rename(columns={
                "fecha_hora": "🕒 FECHA Y HORA",
                "nro_boleta": "🧾 NRO. BOLETA",
                "detalle_articulos": "📦 DETALLE ARTÍCULOS",
                "entrega": "🛵 ENTREGA",
                "metodo_pago": "💳 MÉTODO PAGO",
                "total": "💰 TOTAL",
                "usuario_email": "📧 EMAIL USUARIO"
            })
            st.dataframe(df_historial, use_container_width=True, hide_index=True)
        else:
            st.caption("Aún no se han registrado transacciones en la base de datos.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 💳 FLUJO DE CAJA POR MÉTODO DE PAGO")
        
        col_ef, col_yp, col_tj = st.columns(3)
        with col_ef:
            st.markdown(f"<div style='background-color:#151515; padding:15px; border-radius:6px; border:1px solid #333; text-align:center;'><span style='font-size:24px;'>💵</span><p style='margin:5px 0 0 0; font-size:13px; color:#888;'>EFECTIVO</p><h4 style='margin:5px 0 0 0; color:#27ae60;'>S/{metodos_pagos['Efectivo']:.2f}</h4></div>", unsafe_allow_html=True)
        with col_yp:
            st.markdown(f"<div style='background-color:#151515; padding:15px; border-radius:6px; border:1px solid #333; text-align:center;'><span style='font-size:24px;'>📱</span><p style='margin:5px 0 0 0; font-size:13px; color:#888;'>YAPE</p><h4 style='margin:5px 0 0 0; color:#27ae60;'>S/{metodos_pagos['Yape']:.2f}</h4></div>", unsafe_allow_html=True)
        with col_tj:
            st.markdown(f"<div style='background-color:#151515; padding:15px; border-radius:6px; border:1px solid #333; text-align:center;'><span style='font-size:24px;'>💳</span><p style='margin:5px 0 0 0; font-size:13px; color:#888;'>TARJETA</p><h4 style='margin:5px 0 0 0; color:#27ae60;'>S/{metodos_pagos['Tarjeta']:.2f}</h4></div>", unsafe_allow_html=True)
    
        if sum(metodos_pagos.values()) > 0:
            st.markdown("<br>", unsafe_allow_html=True)
            df_pagos = pd.DataFrame({
                'Método': list(metodos_pagos.keys()),
                'Monto': list(metodos_pagos.values())
            })
            pie = alt.Chart(df_pagos).mark_arc(innerRadius=50, outerRadius=120).encode(
                theta=alt.Theta('Monto:Q'),
                color=alt.Color('Método:N', scale=alt.Scale(domain=['Efectivo','Yape','Tarjeta'], range=['#27ae60','#d35400','#3498db']), legend=alt.Legend(titleColor='#fff', labelColor='#fff')),
                tooltip=['Método:N', alt.Tooltip('Monto:Q', format='.2f')]
            ).properties(width=350, height=300, title=alt.TitleParams('Distribución de Pagos', color='#f39c12', fontSize=16))
            st.altair_chart(pie, use_container_width=True)

    st.markdown("<br><hr><br>", unsafe_allow_html=True)
    # ============================================================================
    # 14B. PANEL DE CONTROL DE ADMINISTRACIÓN - GESTIÓN DE MESAS Y RESERVAS
    # ============================================================================
    if puede_ver(rol_actual, "mesas_reservas"):
        _editar_mr = puede_editar(rol_actual, "mesas_reservas")
        st.markdown("### 🪑 GESTIÓN DE MESAS Y RESERVAS")
        if not _editar_mr:
            st.info("👁️ Modo solo lectura — puedes ver mesas y reservas pero no modificarlas.")
        
        col_mesas_admin, col_reservas_admin = st.columns(2)
        
        with col_mesas_admin:
            st.markdown("#### 🪑 Mesas del Local")
            mesas_admin = database.obtener_mesas()
            
            if mesas_admin:
                for mesa in mesas_admin:
                    nro = int(mesa.get("nro_mesa", 0))
                    estado = str(mesa.get("estado", "disponible")).strip().lower()
                    icono_estado = "🟢" if estado == "disponible" else "🔴"
                    
                    col_m1, col_m2, col_m3 = st.columns([2, 2, 1])
                    with col_m1:
                        st.markdown(f"{icono_estado} **Mesa {nro}** — {estado.upper()}")
                    with col_m2:
                        nuevo_estado = "ocupada" if estado == "disponible" else "disponible"
                        label_btn = f"Marcar {'Ocupada' if estado == 'disponible' else 'Libre'}"
                        if st.button(label_btn, key=f"btn_toggle_mesa_{nro}", use_container_width=True, disabled=not _editar_mr):
                            database.actualizar_estado_mesa(nro, nuevo_estado)
                            st.rerun()
                    with col_m3:
                        if st.button("🗑️", key=f"btn_del_mesa_{nro}", disabled=not _editar_mr):
                            database.eliminar_mesa(nro)
                            st.toast(f"Mesa {nro} eliminada", icon="🗑️")
                            st.rerun()
            else:
                st.info("No hay mesas configuradas.")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Agregar Nueva Mesa", key="btn_add_mesa", use_container_width=True, disabled=not _editar_mr):
                nueva = database.agregar_mesa()
                if nueva:
                    st.toast(f"Mesa {nueva} agregada", icon="✅")
                    st.rerun()
        
        with col_reservas_admin:
            st.markdown("#### 📅 Reservaciones Activas")
            reservas_admin = database.obtener_reservas()
            
            if reservas_admin:
                for reserva in reservas_admin:
                    r_id = reserva.get("id", "?")
                    # Quitar decimal del ID si viene de pandas
                    if str(r_id).endswith(".0"):
                        r_id = str(r_id)[:-2]
                    r_nombre = reserva.get("nombre", "?")
                    r_mesa = reserva.get("nro_mesa", "?")
                    if str(r_mesa).endswith(".0"):
                        r_mesa = str(r_mesa)[:-2]
                    r_fecha = reserva.get("fecha", "?")
                    r_hora = reserva.get("hora", "?")
                    r_tel = reserva.get("datos_contacto", "")
                    r_personas = reserva.get("personas", "2")
                    if str(r_personas).endswith(".0"):
                        r_personas = str(r_personas)[:-2]
                    r_nombres = reserva.get("nombres_invitados", "")
                    
                    # Formatear el teléfono limpio quitando decimales (.0)
                    clean_tel = str(r_tel).split(".")[0].strip()
                    mensaje_wa = f"Hola {r_nombre}, te escribimos de Carnes & Bytes sobre tu reserva #{r_id} de la Mesa {r_mesa} para el día {r_fecha} a las {r_hora}."
                    mensaje_encoded = urllib.parse.quote(mensaje_wa)
                    wa_url = f"https://wa.me/51{clean_tel}?text={mensaje_encoded}"
                    
                    st.markdown(
                        f"<div class='status-strip' style='border-color: #f39c12; padding: 12px 18px !important; margin-bottom: 8px !important;'>"
                        f"<div style='line-height:1.4; text-align: left;'>"
                        f"<strong style='color:#fff; font-size: 14px;'>#{r_id} — {r_nombre}</strong><br>"
                        f"<span style='font-size:12px; color:#aaa;'>🪑 Mesa {r_mesa} | 📆 {r_fecha} | 🕐 {r_hora}</span><br>"
                        f"<span style='font-size:12px; color:#888;'>📱 Tel: {clean_tel} | 👥 {r_personas} integrantes</span><br>"
                        f"<span style='font-size:11px; color:#f39c12;'>📝 Integrantes: {r_nombres}</span>"
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    col_btn_r1, col_btn_r2 = st.columns(2)
                    with col_btn_r1:
                        st.link_button("💬 Enviar WhatsApp", wa_url, use_container_width=True)
                    with col_btn_r2:
                        if st.button(f"❌ Cancelar #{r_id}", key=f"btn_cancel_reserva_{r_id}", use_container_width=True, disabled=not _editar_mr):
                            database.eliminar_reserva(r_id)
                            st.toast(f"Reserva #{r_id} cancelada", icon="❌")
                            st.rerun()
            else:
                st.info("No hay reservaciones activas.")

        st.markdown("<br><hr><br>", unsafe_allow_html=True)
elif not es_admin_autenticado or (es_admin_autenticado and st.session_state.rol_actual is not None):

    # ============================================================================
    # 15. ENTORNO CLIENTE - PANTALLA 1: BIENVENIDA MULTIMEDIA PREMIUM
    # ============================================================================
    if st.session_state.pantalla_actual == "bienvenida":
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<h2 class='titulo-principal'>🔥 CARNES & BYTES — Tu gusto, nuestra meta</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; font-size: 18px; color: #ffffff;'>¿Desea registrar un nuevo pedido de nuestra deliciosa parrilla?</p>", unsafe_allow_html=True)
        estado_servicio = "ABIERTO" if servicio_abierto else "CERRADO"
        color_estado = "#2ecc71" if servicio_abierto else "#e74c3c"
        st.markdown(
            f"<div class='status-strip' style='border-color:{color_estado};'>"
            f"<strong style='color:{color_estado};'>{estado_servicio}</strong>"
            f"<span>Atención: {HORA_APERTURA}:00 - {HORA_CIERRE}:00 | Recojo 15-20 min | Delivery 30-45 min</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        if not servicio_abierto:
            st.warning("Los pedidos están deshabilitados por horario de atención o pausa operativa.")
        st.markdown("<br>", unsafe_allow_html=True)
        
        if servicio_abierto:
            col_opt1, col_opt2, col_opt3 = st.columns(3, gap="medium")
            with col_opt1:
                st.markdown("""
                <div style='background-color:#151515; padding:20px; border-radius:12px; border:2px solid #2ecc71; text-align:center; height:200px; display:flex; flex-direction:column; justify-content:space-between;'>
                    <div>
                        <span style='font-size:35px;'>🪑</span>
                        <h3 style='margin:10px 0 5px 0; color:#2ecc71; font-size:16px;'>Pedido en Salón</h3>
                        <p style='font-size:11px; color:#888; margin:0;'>Elige tu mesa, ingresa tu nombre y haz tu pedido desde tu mesa.</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("<div style='margin-top:-25px;'></div>", unsafe_allow_html=True)
                if st.button("🍽️ PEDIR EN SALÓN", use_container_width=True, key="btn_empezar_pedido_salon"):
                    st.session_state.solo_navegar = False
                    st.session_state.tipo_servicio = "salon"
                    st.session_state.pantalla_actual = "seleccion_mesa"
                    st.session_state.boleta_emitida = False
                    st.rerun()

            with col_opt2:
                st.markdown("""
                <div style='background-color:#151515; padding:20px; border-radius:12px; border:2px solid #e67e22; text-align:center; height:200px; display:flex; flex-direction:column; justify-content:space-between;'>
                    <div>
                        <span style='font-size:35px;'>🛵</span>
                        <h3 style='margin:10px 0 5px 0; color:#e67e22; font-size:16px;'>Pedido por Delivery</h3>
                        <p style='font-size:11px; color:#888; margin:0;'>Ingresa tu dirección de entrega y recibe tu pedido en la puerta de tu hogar.</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("<div style='margin-top:-25px;'></div>", unsafe_allow_html=True)
                if st.button("🛵 PEDIR POR DELIVERY", use_container_width=True, key="btn_empezar_pedido_delivery"):
                    st.session_state.solo_navegar = False
                    st.session_state.tipo_servicio = "delivery"
                    st.session_state.pantalla_actual = "registro_delivery"
                    st.session_state.boleta_emitida = False
                    st.rerun()

            with col_opt3:
                st.markdown("""
                <div style='background-color:#151515; padding:20px; border-radius:12px; border:2px solid #3498db; text-align:center; height:200px; display:flex; flex-direction:column; justify-content:space-between;'>
                    <div>
                        <span style='font-size:35px;'>👁️</span>
                        <h3 style='margin:10px 0 5px 0; color:#3498db; font-size:16px;'>Solo Navegar</h3>
                        <p style='font-size:11px; color:#888; margin:0;'>Revisa los deliciosos platos, precios e ingredientes de nuestra carta.</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("<div style='margin-top:-25px;'></div>", unsafe_allow_html=True)
                if st.button("📖 VER LA CARTA", use_container_width=True, key="btn_empezar_solo_navegar"):
                    st.session_state.solo_navegar = True
                    st.session_state.tipo_servicio = "navegar"
                    st.session_state.mesa_seleccionada = None
                    st.session_state.nombre_cliente = ""
                    st.session_state.direccion_cliente = ""
                    st.session_state.pantalla_actual = "catalogo"
                    st.session_state.boleta_emitida = False
                    st.rerun()
        
        # Botón de reservación cuando el servicio está cerrado
        if not servicio_abierto:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; font-size: 16px; color: #f39c12;'>¿No puedes venir ahora? ¡Reserva tu mesa para cuando abramos!</p>", unsafe_allow_html=True)
            if st.button("📅 HACER UNA RESERVACIÓN", use_container_width=True, key="btn_reservar_bienvenida"):
                if st.session_state.user_info:
                    st.session_state.pantalla_actual = "reservas"
                    st.rerun()
                else:
                    st.session_state.mostrar_login_reserva = True
                    st.rerun()
        
        # Modal de aviso: debe iniciar sesión para reservar
        if st.session_state.get("mostrar_login_reserva", False):
            auth_url = get_google_auth_url()
            st.markdown(f"""
            <div style='background: rgba(15,15,15,0.95); border: 2px solid #f39c12; border-radius: 16px; padding: 30px; text-align: center; margin: 20px auto; max-width: 450px; box-shadow: 0 10px 40px rgba(0,0,0,0.6);'>
                <p style='font-size: 40px; margin-bottom: 10px;'>🔒</p>
                <h3 style='color: #fff; margin-bottom: 10px;'>Inicia Sesión para Reservar</h3>
                <p style='color: #aaa; font-size: 14px; margin-bottom: 20px;'>Para realizar una reservación necesitas tener una cuenta. Inicia sesión con Google y accede a todos los beneficios.</p>
                <a href='{auth_url}' target='_blank' style='display: inline-block; background: linear-gradient(135deg, #f39c12, #e67e22); color: #000; font-weight: 800; padding: 12px 30px; border-radius: 50px; text-decoration: none; font-size: 15px;'>🔑 Iniciar Sesión con Google</a>
            </div>
            """, unsafe_allow_html=True)
            if st.button("✖ Cerrar", key="btn_cerrar_login_reserva"):
                st.session_state.mostrar_login_reserva = False
                st.rerun()
            
        # Bloque de Redes Sociales Corporativas de Carnes & Bytes
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("""
            <div class='social-footer'>
                <p style='margin-bottom: 10px; font-size: 14px; letter-spacing: 2px; color: #888; font-weight: bold;'>SÍGUENOS EN REDES SOCIALES</p>
                <a href='https://www.facebook.com' target='_blank' class='social-icon'>📘 Facebook</a> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
                <a href='https://instagram.com' target='_blank' class='social-icon'>📸 Instagram</a> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
                <a href='https://wa.me/51982174847' target='_blank' class='social-icon'>🟢 WhatsApp</a>
            </div>
        """, unsafe_allow_html=True)


    # ============================================================================
    # 15B. ENTORNO CLIENTE - SELECCIÓN DE MESA
    # ============================================================================
    elif st.session_state.pantalla_actual == "seleccion_mesa":
        st.markdown("<h2 class='titulo-principal'>🪑 Selecciona tu Mesa</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #aaa; font-size: 15px;'>Elige una mesa disponible para iniciar tu pedido</p>", unsafe_allow_html=True)
        
        mesas = database.obtener_mesas()
        if not mesas:
            st.warning("No hay mesas configuradas. Contacta al administrador.")
        else:
            # CSS para la cuadrícula de mesas
            st.markdown("""
            <style>
            .mesa-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; max-width: 600px; margin: 20px auto; }
            @media (max-width: 768px) { .mesa-grid { grid-template-columns: repeat(4, 1fr); gap: 8px; } }
            </style>
            """, unsafe_allow_html=True)
            
            # Generar HTML visual de mesas
            mesa_html = "<div class='mesa-grid'>"
            for mesa in mesas:
                nro = int(mesa.get("nro_mesa", 0))
                estado = str(mesa.get("estado", "disponible")).strip().lower()
                if estado == "ocupada":
                    mesa_html += f"<div style='background: rgba(231,76,60,0.3); border: 2px solid #e74c3c; border-radius: 12px; padding: 15px 10px; text-align: center; opacity: 0.6;'><span style='font-size: 22px;'>🪑</span><br><span style='color: #e74c3c; font-size: 13px; font-weight: 700;'>Mesa {nro}</span><br><span style='font-size: 10px; color: #e74c3c;'>OCUPADA</span></div>"
                else:
                    mesa_html += f"<div style='background: rgba(46,204,113,0.15); border: 2px solid #2ecc71; border-radius: 12px; padding: 15px 10px; text-align: center;'><span style='font-size: 22px;'>🪑</span><br><span style='color: #2ecc71; font-size: 13px; font-weight: 700;'>Mesa {nro}</span><br><span style='font-size: 10px; color: #2ecc71;'>LIBRE</span></div>"
            mesa_html += "</div>"
            st.markdown(mesa_html, unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Selector nativo de Streamlit para elegir mesa
            mesas_disponibles = [int(m["nro_mesa"]) for m in mesas if str(m.get("estado", "")).strip().lower() != "ocupada"]
            
            if not mesas_disponibles:
                st.error("🚫 Todas las mesas están ocupadas en este momento. Intenta más tarde.")
            else:
                nombre_cliente_input = st.text_input("Ingresa tu Nombre completo:", value=st.session_state.get("nombre_cliente", ""), placeholder="Ej: Jhohan Gomez", key="input_nombre_cliente")
                mesa_elegida = st.selectbox("Selecciona tu mesa:", mesas_disponibles, format_func=lambda x: f"🪑 Mesa {x}", key="select_mesa")
                
                col_mesa1, col_mesa2 = st.columns(2)
                with col_mesa1:
                    if st.button("⬅️ Volver", use_container_width=True, key="btn_volver_mesa"):
                        st.session_state.pantalla_actual = "bienvenida"
                        st.rerun()
                with col_mesa2:
                    if st.button("✅ Confirmar Mesa y Pedir", use_container_width=True, key="btn_confirmar_mesa", type="primary"):
                        if not nombre_cliente_input.strip():
                            st.error("⚠️ Por favor ingresa tu nombre antes de continuar.")
                        else:
                            val_nombre = nombre_cliente_input.strip()
                            st.session_state.nombre_cliente = val_nombre
                            st.session_state.cliente_nombre = val_nombre
                            st.session_state.mesa_seleccionada = mesa_elegida
                            # Cambiar estado en GSheets y vaciar caché DESPUÉS para que se propague
                            database.actualizar_estado_mesa(mesa_elegida, "ocupada")
                            st.cache_data.clear()
                            st.session_state.pantalla_actual = "catalogo"
                            st.session_state.boleta_emitida = False
                            st.rerun()

    # ============================================================================
    # 15B-2. ENTORNO CLIENTE - REGISTRO DE DELIVERY
    # ============================================================================
    elif st.session_state.pantalla_actual == "registro_delivery":
        st.markdown("<h2 class='titulo-principal'>🛵 Datos de Entrega</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #aaa; font-size: 15px;'>Ingresa tus datos para realizar el envío de tu pedido a domicilio</p>", unsafe_allow_html=True)
        
        with st.container(border=True):
            nombre_del = st.text_input("Ingresa tu Nombre completo:", value=st.session_state.get("nombre_cliente", ""), placeholder="Ej: Jhohan Gomez", key="input_nombre_del")
            direccion_del = st.text_input("Dirección exacta de entrega (ej: Av. Larco 123, Trujillo):", value=st.session_state.get("direccion_cliente", ""), placeholder="Ej: Calle Principal 456, Urb. El Recreo", key="input_direccion_del")
            
            st.markdown("<br>", unsafe_allow_html=True)
            col_del1, col_del2 = st.columns(2)
            with col_del1:
                if st.button("⬅️ Volver", use_container_width=True, key="btn_volver_del"):
                    st.session_state.pantalla_actual = "bienvenida"
                    st.rerun()
            with col_del2:
                if st.button("✅ Confirmar y Ver Carta", use_container_width=True, key="btn_confirmar_del", type="primary"):
                    if not nombre_del.strip():
                        st.error("⚠️ Por favor ingresa tu nombre antes de continuar.")
                    elif not direccion_del.strip():
                        st.error("⚠️ Por favor ingresa la dirección de entrega antes de continuar.")
                    else:
                        val_nombre_del = nombre_del.strip()
                        st.session_state.nombre_cliente = val_nombre_del
                        st.session_state.cliente_nombre = val_nombre_del
                        st.session_state.direccion_cliente = direccion_del.strip()
                        st.session_state.mesa_seleccionada = None
                        st.session_state.pantalla_actual = "catalogo"
                        st.session_state.boleta_emitida = False
                        st.rerun()


    # ============================================================================
    # 15C. ENTORNO CLIENTE - PANTALLA DE RESERVACIONES
    # ============================================================================
    elif st.session_state.pantalla_actual == "reservas":
        if not st.session_state.user_info:
            auth_url = get_google_auth_url()
            st.markdown(f"""
            <div style='background: rgba(15,15,15,0.95); border: 2px solid #f39c12; border-radius: 16px; padding: 40px; text-align: center; margin: 40px auto; max-width: 500px; box-shadow: 0 10px 40px rgba(0,0,0,0.6);'>
                <p style='font-size: 50px; margin-bottom: 15px;'>🔒</p>
                <h2 style='color: #fff; margin-bottom: 10px;'>Inicia Sesión para Reservar</h2>
                <p style='color: #aaa; font-size: 15px; margin-bottom: 25px;'>Para realizar una reservación necesitas tener una cuenta registrada. Inicia sesión con Google y disfruta de nuestros beneficios exclusivos.</p>
                <a href='{auth_url}' target='_blank' style='display: inline-block; background: linear-gradient(135deg, #f39c12, #e67e22); color: #000; font-weight: 800; padding: 14px 35px; border-radius: 50px; text-decoration: none; font-size: 16px;'>🔑 Iniciar Sesión con Google</a>
            </div>
            """, unsafe_allow_html=True)
            if st.button("⬅️ Volver al Inicio", use_container_width=True, key="btn_volver_reserva_login"):
                st.session_state.pantalla_actual = "bienvenida"
                st.rerun()
        else:
            u_info = st.session_state.user_info
            st.markdown("<h2 class='titulo-principal'>📅 Reservar tu Mesa</h2>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; color: #aaa;'>Reservando como <strong style='color:#f39c12;'>{u_info.get('name','')}</strong></p>", unsafe_allow_html=True)
            
            mesas = database.obtener_mesas(ttl=5)
            mesas_disponibles = [int(m["nro_mesa"]) for m in mesas if str(m.get("estado", "")).strip().lower() != "ocupada"]
            
            if not mesas_disponibles:
                st.error("🚫 No hay mesas disponibles para reservar en este momento.")
            else:
                import datetime as dt_module
                with st.form("form_reserva", clear_on_submit=True):
                    st.markdown("#### Datos de tu reservación")
                    
                    col_r1, col_r2 = st.columns(2)
                    with col_r1:
                        fecha_reserva = st.date_input("📆 Fecha", min_value=dt_module.date.today(), key="input_fecha_reserva")
                    with col_r2:
                        hora_reserva = st.time_input("🕐 Hora", value=dt_module.time(19, 0), key="input_hora_reserva")
                    
                    mesa_reserva = st.selectbox("🪑 Mesa", mesas_disponibles, format_func=lambda x: f"Mesa {x}", key="select_mesa_reserva")
                    col_r3, col_r4 = st.columns(2)
                    with col_r3:
                        personas = st.number_input("👥 Cantidad de integrantes", min_value=1, max_value=15, value=2, step=1, key="input_cant_reserva")
                    with col_r4:
                        nombres_invitados = st.text_input("📝 Nombres de los integrantes", placeholder="Ej: Jhohan, María, Carlos...", key="input_invitados_reserva")
                        
                    telefono = st.text_input("📱 Teléfono de contacto", placeholder="Ej: 987654321", key="input_tel_reserva")
                    
                    submitted = st.form_submit_button("✅ Confirmar Reservación", use_container_width=True, type="primary")
                    
                    if submitted:
                        if not telefono.strip():
                            st.error("Por favor ingresa un teléfono de contacto.")
                        elif not nombres_invitados.strip():
                            st.error("Por favor ingresa los nombres de los integrantes.")
                        else:
                            resultado = database.crear_reserva(
                                email=u_info.get("email", ""),
                                nombre=u_info.get("name", ""),
                                nro_mesa=mesa_reserva,
                                fecha=str(fecha_reserva),
                                hora=str(hora_reserva),
                                datos_contacto=telefono.strip(),
                                personas=int(personas),
                                nombres_invitados=nombres_invitados.strip()
                            )
                            if resultado:
                                st.success(f"🎉 ¡Reservación #{resultado} confirmada! Mesa {mesa_reserva} el {fecha_reserva} a las {hora_reserva}.")
                                st.balloons()
                            else:
                                st.error("Error al crear la reservación. Intente nuevamente.")
                
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("⬅️ Volver al Inicio", use_container_width=True, key="btn_volver_reserva"):
                st.session_state.pantalla_actual = "bienvenida"
                st.rerun()


    # ============================================================================
    # 15D. ENTORNO CLIENTE - MIS RESERVAS
    # ============================================================================
    elif st.session_state.pantalla_actual == "mis_reservas":
        st.markdown("<h2 class='titulo-principal'>📌 Mis Reservas</h2>", unsafe_allow_html=True)
        
        if not st.session_state.user_info:
            st.warning("Debes iniciar sesión para ver tus reservas.")
        else:
            email_usuario = st.session_state.user_info.get("email", "").strip().lower()
            todas_reservas = database.obtener_reservas(ttl=5)
            mis_reservas = [r for r in todas_reservas if str(r.get("email", "")).strip().lower() == email_usuario]
            
            if not mis_reservas:
                st.markdown("""
                <div style='text-align: center; padding: 50px 20px;'>
                    <p style='font-size: 60px; margin-bottom: 15px;'>📅</p>
                    <h3 style='color: #fff; margin-bottom: 10px;'>Aún no tienes reservas</h3>
                    <p style='color: #888; font-size: 14px;'>Cuando hagas una reservación, aparecerá aquí para que puedas verla y gestionarla.</p>
                </div>
                """, unsafe_allow_html=True)
                if st.button("📅 Hacer mi primera reserva", use_container_width=True, key="btn_primera_reserva", type="primary"):
                    st.session_state.pantalla_actual = "reservas"
                    st.rerun()
            else:
                st.markdown(f"<p style='text-align:center; color:#aaa;'>Tienes <strong style='color:#f39c12;'>{len(mis_reservas)}</strong> reserva(s) activa(s)</p>", unsafe_allow_html=True)
                for reserva in mis_reservas:
                    r_id = reserva.get("id", "?")
                    if str(r_id).endswith(".0"):
                        r_id = str(r_id)[:-2]
                    r_mesa = reserva.get("nro_mesa", "?")
                    if str(r_mesa).endswith(".0"):
                        r_mesa = str(r_mesa)[:-2]
                    r_fecha = reserva.get("fecha", "?")
                    r_hora = reserva.get("hora", "?")
                    r_tel = reserva.get("datos_contacto", "")
                    clean_tel = str(r_tel).split(".")[0].strip()
                    r_personas = reserva.get("personas", "2")
                    if str(r_personas).endswith(".0"):
                        r_personas = str(r_personas)[:-2]
                    r_nombres = reserva.get("nombres_invitados", "")
                    
                    st.markdown(
                        f"<div style='background: rgba(243,156,18,0.08); border: 1.5px solid rgba(243,156,18,0.4); border-radius: 14px; padding: 18px 20px; margin-bottom: 12px; text-align: left;'>"
                        f"<span style='font-size: 14px; font-weight: 800; color: #f39c12;'>Reserva #{r_id}</span><br>"
                        f"<span style='font-size: 13px; color: #ddd;'>🪑 Mesa {r_mesa}  &nbsp;|&nbsp;  📆 {r_fecha}  &nbsp;|&nbsp;  🕐 {r_hora}</span><br>"
                        f"<span style='font-size: 12px; color: #888;'>📱 Tel: {clean_tel} &nbsp;|&nbsp; 👥 {r_personas} integrantes</span><br>"
                        f"<span style='font-size: 12px; color: #aaa;'>📝 Integrantes: {r_nombres}</span>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    if st.button(f"❌ Cancelar Reserva #{r_id}", key=f"btn_cancel_mi_reserva_{r_id}", use_container_width=True):
                        database.eliminar_reserva(r_id)
                        st.toast(f"Reserva #{r_id} cancelada exitosamente", icon="✅")
                        st.rerun()
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⬅️ Volver al Inicio", use_container_width=True, key="btn_volver_mis_reservas"):
            st.session_state.pantalla_actual = "bienvenida"
            st.rerun()


    # ============================================================================
    # 16. ENTORNO CLIENTE - PANTALLA 2: CATÁLOGO DINÁMICO DE PRODUCTOS
    # ============================================================================
    elif st.session_state.pantalla_actual == "catalogo" and not st.session_state.pedido_guardado:
        if st.session_state.get("tipo_servicio", "salon") == "navegar" or st.session_state.get("solo_navegar", False):
            st.markdown("""
            <div style='background-color:rgba(52,152,219,0.12); border:1px solid #3498db; color:#54aeff; padding:10px 16px; border-radius:8px; font-size:14px; text-align:center; font-weight:bold; margin-bottom:15px;'>
                👁️ MODO CONSULTA — Estás navegando la carta digital. No es posible agregar productos al carrito.
            </div>
            """, unsafe_allow_html=True)
        elif st.session_state.get("tipo_servicio") == "delivery":
            render_stepper(1)
            cli_nom = st.session_state.get("nombre_cliente", "Cliente")
            cli_dir = st.session_state.get("direccion_cliente", "No indicada")
            st.markdown(f"""
            <div style='background-color:rgba(230,126,34,0.12); border:1px solid #e67e22; color:#e67e22; padding:10px 16px; border-radius:8px; font-size:14px; text-align:center; font-weight:bold; margin-bottom:15px;'>
                👤 Cliente: {cli_nom} &nbsp;|&nbsp; 🛵 Envío a: {cli_dir} &nbsp;|&nbsp; 🛒 Listo para armar tu pedido
            </div>
            """, unsafe_allow_html=True)
        else: # salon
            render_stepper(1)
            cli_nom = st.session_state.get("nombre_cliente", "Cliente")
            cli_mesa = st.session_state.get("mesa_seleccionada", "?")
            st.markdown(f"""
            <div style='background-color:rgba(46,204,113,0.12); border:1px solid #2ecc71; color:#2ecc71; padding:10px 16px; border-radius:8px; font-size:14px; text-align:center; font-weight:bold; margin-bottom:15px;'>
                👤 Cliente: {cli_nom} &nbsp;|&nbsp; 🪑 Mesa: {cli_mesa} &nbsp;|&nbsp; 🛒 Listo para armar tu pedido
            </div>
            """, unsafe_allow_html=True)
            

            
        st.markdown("\n<h2 class='titulo-principal'>🔥 CARNES & BYTES — Tu gusto, nuestra meta</h2>", unsafe_allow_html=True)
        st.text(f"Fecha y hora oficial de Perú (GMT-5): {fecha_actual}\n")
        
        st.subheader(f"🍽️ SELECCIÓN DE {st.session_state.categoria_activa.upper()}")
        
        if st.session_state.get("solo_navegar", False):
            st.info("Echa un vistazo a nuestros platos y especialidades:")
        else:
            st.info("Ingrese las cantidades de los productos que desea llevar:")
            
        if not servicio_abierto:
            st.warning("El catálogo está visible, pero no se pueden confirmar pedidos fuera del horario de atención.")

        col_filtro1, col_filtro2 = st.columns(2)
        with col_filtro1:
            filtro_catalogo = st.selectbox(
                "Filtro rápido",
                ["Todos", "Disponibles", "Últimas unidades", "Agotados", "Más vendido"],
                key="filtro_catalogo_cliente",
            )
        with col_filtro2:
            orden_catalogo = st.selectbox(
                "Ordenar por",
                ["Carta original", "Menor precio", "Mayor precio", "Mayor stock"],
                key="orden_catalogo_cliente",
            )

        productos_lista = list(st.session_state.menu_dinamico.keys())
        productos_filtrados = []
        producto_mas_vendido = max(conteos_productos, key=lambda k: conteos_productos[k]) if conteos_productos and max(conteos_productos.values()) > 0 else None

        for prod in productos_lista:
            if busqueda and busqueda not in prod.lower():
                continue
                
            info_prod = st.session_state.menu_dinamico[prod]
            cat_prod = info_prod.get("categoria", "Parrillas")
            stock_prod = int(info_prod.get("stock", 0))
            disponible_prod = bool(info_prod.get("disponible", False)) and stock_prod > 0

            if st.session_state.categoria_activa == "Todos" or st.session_state.categoria_activa == cat_prod:
                if filtro_catalogo == "Disponibles" and not disponible_prod:
                    continue
                if filtro_catalogo == "Últimas unidades" and not (0 < stock_prod <= 3):
                    continue
                if filtro_catalogo == "Agotados" and stock_prod > 0:
                    continue
                if filtro_catalogo == "Más vendido" and prod != producto_mas_vendido:
                    continue
                productos_filtrados.append(prod)

        if orden_catalogo == "Menor precio":
            productos_filtrados.sort(key=lambda p: float(st.session_state.menu_dinamico[p].get("precio", 0)))
        elif orden_catalogo == "Mayor precio":
            productos_filtrados.sort(key=lambda p: float(st.session_state.menu_dinamico[p].get("precio", 0)), reverse=True)
        elif orden_catalogo == "Mayor stock":
            productos_filtrados.sort(key=lambda p: int(st.session_state.menu_dinamico[p].get("stock", 0)), reverse=True)

        if not productos_filtrados:
            st.warning("No hay productos para el filtro seleccionado.")

        col1, col2 = st.columns(2, gap="medium")
        cantidades_ingresadas = {}
        
        for i in range(len(productos_filtrados)):
            prod = productos_filtrados[i]
            info = st.session_state.menu_dinamico[prod]
            target_col = col1 if i % 2 == 0 else col2
            
            stock_actual = info.get("stock", 0)
            esta_disponible = info["disponible"] and stock_actual > 0
            
            with target_col:
                prod_html = escapar_html(prod)
                icono_html = escapar_html(info.get("icono", ""))
                if esta_disponible:
                    if prod == producto_mas_vendido:
                        st.markdown("<div style='background:linear-gradient(135deg,#f39c12,#e67e22);color:#fff;padding:4px 12px;border-radius:20px;display:inline-block;font-size:12px;font-weight:800;margin-bottom:5px;'>👑 MÁS VENDIDO</div>", unsafe_allow_html=True)
                    if stock_actual <= 3:
                        st.markdown("<div class='badge-soft'>ÚLTIMAS UNIDADES</div>", unsafe_allow_html=True)
                    url_imagen_plato = info.get("foto", "")
                    src_imagen_plato = obtener_src_foto(url_imagen_plato)
                    is_fav = prod in st.session_state.favoritos
                    st.markdown(f"""
                        <div style="position:relative;">
                            <img src="{escapar_html(src_imagen_plato)}" style="width:100%; height:200px; object-fit:cover; border-radius:12px 12px 0px 0px; box-shadow: 0px 4px 12px rgba(0,0,0,0.6); display:block; margin:0; padding:0;">
                        </div>
                    """, unsafe_allow_html=True)
                    
                    nuevo_fav = st.checkbox("❤️ Favorito", value=is_fav, key=f"fav_{prod}")
                    if nuevo_fav != is_fav:
                        if nuevo_fav:
                            st.session_state.favoritos.add(prod)
                        else:
                            st.session_state.favoritos.remove(prod)
                        st.rerun()
                    
                    texto_precio = f"S/{info['precio']:.2f}"
                    
                    st.markdown(f"""
                        <div class='product-card-bottom'>
                            <span class='product-title'>{icono_html} {prod_html}</span>
                            <span class='product-price'>{texto_precio}</span>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    if stock_actual <= 3:
                        st.markdown(f"<p class='mini-stock-alerta'>🔥 ¡Solo quedan {stock_actual} unidades! 🔥</p>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<p class='mini-stock-normal'>📦 Stock disponible: {stock_actual} und.</p>", unsafe_allow_html=True)
                    
                    if st.session_state.get("solo_navegar", False):
                        st.markdown("<div style='height:15px;'></div>", unsafe_allow_html=True)
                    else:
                        cantidades_ingresadas[prod] = st.number_input(
                            f"Cantidad de {prod}:", min_value=0, max_value=int(stock_actual), step=1, key=f"cat_{prod}", label_visibility="collapsed"
                        )
                    st.markdown("<br>", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div style="width:100%; height:200px; background-color:#222; border-radius:12px 12px 0px 0px; display:flex; align-items:center; justify-content:center;"><span style="font-size:50px; filter:grayscale(100%);">{icono_html}</span></div>""", unsafe_allow_html=True)
                    st.markdown(f"<div style='background-color:#151515; padding:20px; border-radius:0px 0px 12px 12px; border:2px solid #ff4b4b; text-align:center; margin-bottom:25px;'><p style='color: #ff4b4b; font-size:18px; font-weight: bold; margin:0;'>❌ {prod_html}<br>(AGOTADO)</p></div>", unsafe_allow_html=True)
        st.markdown("---")
        
        if st.session_state.get("solo_navegar", False):
            if st.button("⬅️ VOLVER AL MENÚ DE INICIO", use_container_width=True, key="btn_volver_bienvenida_solo_nav"):
                st.session_state.pantalla_actual = "bienvenida"
                st.rerun()
        else:
            resumen_previo = []
            total_previo = 0.0
            for prod, cant in cantidades_ingresadas.items():
                if cant > 0:
                    subtotal_previo = cant * st.session_state.menu_dinamico[prod]["precio"]
                    resumen_previo.append(f"{cant}x {prod}")
                    total_previo += subtotal_previo
            if resumen_previo:
                st.info(f"Carrito actual: {', '.join(resumen_previo)} | Total parcial: S/{total_previo:.2f}")
                st.markdown(f"""
                    <div class="floating-cart-bar">
                        <div class="cart-summary">🛒 {len(resumen_previo)} ítems seleccionados</div>
                        <div class="cart-total">Total: S/{total_previo:.2f}</div>
                    </div>
                """, unsafe_allow_html=True)

            if st.button("🛒 ENVIAR PEDIDO Y CONFIGURAR PAGO", use_container_width=True, disabled=not servicio_abierto):
                st.session_state.carrito = []
                st.session_state.total_acumulado = 0.0
                for prod, cant in cantidades_ingresadas.items():
                    if cant > 0:
                        sub = cant * st.session_state.menu_dinamico[prod]["precio"]
                        st.session_state.carrito.append({"producto": prod, "cantidad": cant, "subtotal": sub})
                        st.session_state.total_acumulado += sub
                
                if st.session_state.total_acumulado > 0:
                    st.session_state.pedido_guardado = True
                    st.session_state.boleta_emitida = False
                    st.rerun()
                else:
                    st.error("⚠️ Error: Debe seleccionar al menos 1 producto.")
    elif st.session_state.pantalla_actual == "mis_pedidos":
        st.subheader("📋 MIS PEDIDOS ANTERIORES")
        if not st.session_state.user_info:
            st.warning("⚠️ Debe iniciar sesión para ver su historial de pedidos.")
            if st.button("Ir al catálogo", use_container_width=True):
                st.session_state.pantalla_actual = "catalogo"
                st.rerun()
        else:
            email_usuario = st.session_state.user_info.get("email", "").strip().lower()
            todas_las_ordenes = database.obtener_ordenes()
            mis_ordenes = [o for o in todas_las_ordenes if str(o.get("Usuario Email", "")).strip().lower() == email_usuario]
            
            if not mis_ordenes:
                st.info("Aún no tienes pedidos registrados con esta cuenta.")
                if st.button("🛒 Empezar mi primer pedido", use_container_width=True):
                    st.session_state.pantalla_actual = "catalogo"
                    st.rerun()
            else:
                st.write(f"Has realizado **{len(mis_ordenes)}** pedidos.")
                
                # Obtener calificaciones para cruzarlas
                ratings = database.obtener_calificaciones()
                rating_dict = {str(r.get("nro_boleta", "")): r for r in ratings}
                
                for orden in mis_ordenes:
                    nro_boleta = orden.get("Nro. Boleta", "")
                    fecha = orden.get("Fecha y Hora", "")
                    total = orden.get("Total", "")
                    detalle = orden.get("Detalle Artículos", "")
                    entrega = orden.get("Entrega", "")
                    metodo_pago = orden.get("Método Pago", "")
                    
                    calif_info = rating_dict.get(nro_boleta)
                    calif_estrellas = f"⭐ {calif_info['calificacion']}/5" if calif_info else "Sin calificar"
                    
                    st.markdown(
                        f"<div class='status-strip' style='border-color: #444; justify-content: space-between !important; padding: 15px !important; margin-bottom: 15px !important; max-width: 100% !important; text-align: left; align-items: flex-start !important;'>"
                        f"<div>"
                        f"<h4 style='margin: 0 0 5px 0; color: #fff;'>Pedido <strong>{nro_boleta}</strong></h4>"
                        f"<div style='color: #aaa; font-size: 13px; margin-bottom: 10px;'>📅 {fecha} | 🛵 {entrega} | 💳 {metodo_pago}</div>"
                        f"<div style='color: #ddd; font-size: 14px; font-family: monospace; white-space: pre-wrap;'>{detalle.strip()}</div>"
                        f"</div>"
                        f"<div style='text-align: right;'>"
                        f"<h3 style='color: #f39c12; margin: 0 0 5px 0;'>{total}</h3>"
                        f"<div style='color: #aaa; font-size: 12px;'>Calif: {calif_estrellas}</div>"
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                            
                st.html("<br>")
                if st.button("⬅️ Volver al catálogo", use_container_width=True, key="btn_volver_mis_pedidos"):
                    st.session_state.pantalla_actual = "catalogo"
                    st.rerun()
    # ============================================================================
    # 17. ENTORNO CLIENTE - PANTALLA 3: PASARELA Y COMPROBACIÓN DE DATOS
    # ============================================================================
    else:
        render_stepper(2)
        st.html("<div style='height: 15px;'></div>")
        st.subheader("📦 GESTIÓN DE ENTREGA Y PAGO")
        
        if not st.session_state.carrito:
            st.warning("No hay productos en el carrito. Volviendo al inicio...")
            st.session_state.pantalla_actual = "bienvenida"
            st.session_state.pedido_guardado = False
            st.session_state.boleta_emitida = False
            st.rerun()
        
        st.markdown("### 🧾 Revisa tu carrito")
        carrito_editado = []
        for idx, item in enumerate(st.session_state.carrito):
            info_prod = st.session_state.menu_dinamico.get(item["producto"], {})
            stock_disponible = int(info_prod.get("stock", item["cantidad"]))
            col_item1, col_item2, col_item3 = st.columns([3, 1, 1])
            with col_item1:
                st.markdown(f"**{info_prod.get('icono', '🍔')} {item['producto']}**")
                st.caption(f"Precio unitario: S/{float(info_prod.get('precio', 0)):.2f} | Stock: {stock_disponible}")
            with col_item2:
                nueva_cantidad = st.number_input(
                    "Cantidad",
                    min_value=0,
                    max_value=max(stock_disponible, int(item["cantidad"])),
                    value=int(item["cantidad"]),
                    step=1,
                    key=f"checkout_qty_{idx}_{sanitizar_nombre(item['producto'])}",
                    label_visibility="collapsed",
                )
            with col_item3:
                quitar = st.button("Quitar", key=f"checkout_remove_{idx}_{sanitizar_nombre(item['producto'])}", use_container_width=True)

            if nueva_cantidad > 0 and not quitar:
                precio = float(info_prod.get("precio", 0))
                carrito_editado.append({
                    "producto": item["producto"],
                    "cantidad": int(nueva_cantidad),
                    "subtotal": precio * int(nueva_cantidad),
                })

        st.session_state.carrito, st.session_state.total_acumulado = recalcular_carrito(carrito_editado)
        if not st.session_state.carrito:
            st.warning("El carrito quedó vacío. Vuelva al catálogo para seleccionar productos.")
            st.stop()
        for item in st.session_state.carrito:
            st.caption(f"{item['cantidad']}x {item['producto']} - S/{item['subtotal']:.2f}")
        
        st.markdown("---")
        col_cliente1, col_cliente2 = st.columns(2)
        with col_cliente1:
            st.session_state.cliente_nombre = st.text_input(
                "Nombre del cliente",
                value=st.session_state.get("nombre_cliente", st.session_state.cliente_nombre),
                placeholder="Ej. María López",
            ).strip()
        with col_cliente2:
            st.session_state.cliente_telefono = st.text_input(
                "Teléfono de contacto",
                value=st.session_state.cliente_telefono,
                placeholder="Ej. 982174847",
            ).strip()

        # Determinación automática de delivery según la selección inicial de bienvenida
        servicio_inicial = st.session_state.get("tipo_servicio", "salon")
        
        if servicio_inicial == "delivery":
            opcion_delivery = "SI"
            st.info("🛵 Pedido registrado como **Delivery**")
        else:
            opcion_delivery = "NO"
            st.info("🪑 Pedido registrado como **Consumo en Salón**")

        direccion_delivery = ""
        costo_delivery = 0.0
        tiene_delivery = False
        
        if opcion_delivery == "SI":
            tiene_delivery = True
            costo_delivery = 6.0
            direccion_delivery = st.text_input(
                "Dirección de entrega:", 
                value=st.session_state.get("direccion_cliente", ""),
                placeholder="Ej. Av. Larco 123..."
            ).strip()
        else:
            st.caption(f"Número de mesa asignado: **Mesa {st.session_state.get('mesa_seleccionada', '?')}**")
            
        st.caption(f"Tiempo estimado: {tiempo_estimado_texto(tiene_delivery)}")

        total_items_checkout = sum(int(item["cantidad"]) for item in st.session_state.carrito)
        
        valor_cupon_defecto = st.session_state.cupon_aplicado
        if st.session_state.user_info and not valor_cupon_defecto:
            db_user = database.obtener_usuario(st.session_state.user_info.get("email", ""))
            # VALIDACIÓN: Solo se aplica automáticamente si es su primera compra (compras_realizadas == 0)
            if db_user and int(db_user.get("compras_realizadas", 0)) == 0:
                nombre_pila = db_user.get("nombre", "").split(" ")[0].upper()
                cupon_bienvenida = f"BIENVENIDO-{nombre_pila}"
                cupones_bd = database.obtener_cupones(ttl=database.TTL_LECTURA)
                if cupon_bienvenida in cupones_bd and cupones_bd[cupon_bienvenida]["activo"]:
                    valor_cupon_defecto = cupon_bienvenida
                    st.session_state.cupon_aplicado = cupon_bienvenida

        st.session_state.cupon_aplicado = st.text_input(
            "Cupón de descuento",
            value=valor_cupon_defecto,
            placeholder="Ingresa un cupón si tienes uno...",
        ).strip().upper()
        descuento, mensaje_cupon = calcular_descuento(
            st.session_state.cupon_aplicado,
            st.session_state.total_acumulado,
            costo_delivery,
            total_items_checkout,
        )
        if mensaje_cupon:
            if descuento > 0:
                st.success(mensaje_cupon)
            else:
                st.warning(mensaje_cupon)

        total_con_delivery = max(0.0, st.session_state.total_acumulado + costo_delivery - descuento)
        col_total1, col_total2, col_total3 = st.columns(3)
        col_total1.metric(label="Subtotal", value=f"S/{st.session_state.total_acumulado:.2f}")
        col_total2.metric(label="Delivery / descuento", value=f"S/{costo_delivery:.2f} / -S/{descuento:.2f}")
        col_total3.metric(label="Monto Total a Procesar", value=f"S/{total_con_delivery:.2f}")

        metodo_pago = st.selectbox("Seleccione método de pago:", ["Efectivo", "Yape", "Tarjeta"])
        
        pago_usuario = total_con_delivery
        vuelto = 0.0
        titular_tarjeta = ""
        ultimos_digitos = ""
        formulario_valido = True

        if metodo_pago == "Yape":
            st.info(f"--- PROCESANDO PAGO CON YAPE ---\nMonto total a yapear: S/{total_con_delivery:.2f}")
            ruta_qr_local = os.path.join(BASE_DIR, "mi_qr_yape-Jhohan.png")
            if not os.path.exists(ruta_qr_local):
                ruta_qr_local = os.path.join(BASE_DIR, "mi_qr_yape de Jhohan.png")
            
            if os.path.exists(ruta_qr_local):
                with open(ruta_qr_local, "rb") as qr_file:
                    encoded_qr = base64.b64encode(qr_file.read()).decode()
                src_imagen_qr = f"data:image/png;base64,{encoded_qr}"
            else:
                src_imagen_qr = "data:image/svg+xml;utf8,<svg xmlns='http://w3.org' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/></svg>"

            st.markdown(f"""
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 25px auto; max-width: 450px; background-color: #151515; padding: 25px; border-radius: 16px; border: 2px solid #d35400; box-shadow: 0px 8px 25px rgba(142, 68, 173, 0.25); text-align: center;">
                    <p style="color: #aaaaaa; font-size: 14px; margin-bottom: 15px; font-weight: bold;">[!] Escanee con la cámara de su celular para pagar:</p>
                    <img src="{src_imagen_qr}" style="width: 260px; height: 260px; object-fit: contain; border-radius: 12px; box-shadow: 0px 4px 15px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.1); margin-bottom: 15px;" />
                    <span style="color: #d35400; font-size: 14px; font-weight: bold; letter-spacing: 1px;">🟣 CÓDIGO QR DE YAPE OFICIAL</span>
                </div>
            """, unsafe_allow_html=True)

        elif metodo_pago == "Tarjeta":
            st.info("--- PROCESANDO TRANSMISIÓN POS ---")
            titular_tarjeta = st.text_input("Ingrese nombre del titular de la tarjeta:").strip().upper()
            ultimos_digitos = st.text_input("Ingrese los últimos 4 dígitos de la tarjeta:", max_chars=4)
            if not titular_tarjeta or len(ultimos_digitos) != 4 or not ultimos_digitos.isdigit():
                st.error("Complete los datos de la tarjeta de manera válida (4 dígitos).")
                formulario_valido = False
                
        else:
            st.warning("SOLO SE ACEPTA MONEDA NACIONAL!\nEste establecimiento NO recibe dólares ni euros.")
            pago_usuario = st.number_input("Ingrese monto de pago: S/", min_value=0.0, value=total_con_delivery, step=1.0)
            if pago_usuario < total_con_delivery:
                st.error("Pago insuficiente")
                formulario_valido = False
            else:
                vuelto = pago_usuario - total_con_delivery

        telefono_normalizado = normalizar_telefono(st.session_state.cliente_telefono)
        if not st.session_state.cliente_nombre:
            st.warning("Ingrese el nombre del cliente para finalizar el pedido.")
            formulario_valido = False
        if len(telefono_normalizado) < 7:
            st.warning("Ingrese un teléfono válido para confirmar o coordinar el pedido.")
            formulario_valido = False

        confirmar_pedido = st.checkbox(
            f"Confirmo emitir este pedido por S/{total_con_delivery:.2f}",
            key="confirmar_pedido_cliente",
        )

        # ============================================================================
        # 18. FINALIZACIÓN Y COUPLING DE DATOS CON LA BOLETA COMPLEMENTARIA HTML
        # ============================================================================
        if st.session_state.get("boleta_emitida", False):
            st.success("Boleta ya emitida. Cree una nueva orden para registrar otra venta.")

        if st.button(
            "💾 EMITIR BOLETA DE VENTA",
            use_container_width=True,
            disabled=st.session_state.get("boleta_emitida", False),
        ):
            tiempo_actual_ts = datetime.now().timestamp()
            tiempo_desde_ultima = tiempo_actual_ts - st.session_state.get("ultima_boleta_time", 0)
            
            if not confirmar_pedido:
                st.error("⚠️ Debe confirmar el pedido marcando la casilla antes de emitir la boleta.")
            elif tiempo_desde_ultima < MIN_SEGUNDOS_ENTRE_BOLETAS:
                st.warning(f"⏳ Por favor espere {int(MIN_SEGUNDOS_ENTRE_BOLETAS - tiempo_desde_ultima)} segundos antes de emitir otra boleta.")
            elif tiene_delivery and not direccion_delivery:
                st.error("⚠️ Error: Llenar este campo obligatorio (Ingrese su dirección de entrega).")
            elif not formulario_valido:
                st.error("⚠️ Error: Complete correctamente los datos del formulario de pago antes de continuar.")
            else:
                stock_valido, menu_actualizado, errores_stock = validar_carrito_con_stock(st.session_state.carrito)
                if not stock_valido:
                    for error_stock in errores_stock:
                        st.warning(f"⚠️ {error_stock}")
                    st.session_state.menu_dinamico = menu_actualizado
                    if not st.session_state.carrito:
                        st.error("🛒 Tu carrito quedó vacío. Serás redirigido al catálogo.")
                        st.session_state.pedido_guardado = False
                        st.session_state.pantalla_actual = "catalogo"
                        import time; time.sleep(2)
                        st.rerun()
                    else:
                        st.info("🔄 Tu carrito fue ajustado. Presiona de nuevo **Emitir Boleta** para continuar.")
                    st.stop()

                historial_actualizado = database.obtener_ordenes()
                numero_boleta_actual = generar_numero_boleta(historial_actualizado)
                correlativo_sunat = f"B001-{numero_boleta_actual:06d}"
                detalle_productos_txt = ""
                items_resumen_lista = []
                
                for item in st.session_state.carrito:
                    producto_boleta = escapar_html(item["producto"])
                    detalle_productos_txt += f"{item['cantidad']}x {producto_boleta:<18} S/{item['subtotal']:.2f}\n"
                    items_resumen_lista.append(f"{item['cantidad']}x {item['producto']}")
                
                if tiene_delivery:
                    detalle_productos_txt += "1x Costo de Envío        S/6.00\n"
                    items_resumen_lista.append("1x Delivery")
                
                resumen_articulos_linea = ", ".join(items_resumen_lista)
                
                if tiene_delivery:
                    tipo_entrega_db = f"DELIVERY ({direccion_delivery})"
                else:
                    tipo_entrega_db = f"SALÓN (Mesa {st.session_state.get('mesa_seleccionada', '?')}) - {st.session_state.cliente_nombre}"
                    
                tipo_entrega_html = escapar_html(tipo_entrega_db)
                
                actualizaciones_stock = {}
                for item in st.session_state.carrito:
                    prod_comprado = item["producto"]
                    cant_comprada = int(item["cantidad"])
                    nuevo_stock = max(0, int(menu_actualizado[prod_comprado].get("stock", 0)) - cant_comprada)
                    actualizaciones_stock[prod_comprado] = nuevo_stock
                
                stock_actualizado = database.actualizar_stock_multiple(None, actualizaciones_stock)

                # Si falla por cuota 429 de escritura, no bloqueamos la venta del cliente.
                # Actualizamos de todas formas el stock local en memoria para mantener coherencia en esta sesión.
                if not stock_actualizado:
                    for p, nuevo_st in actualizaciones_stock.items():
                        if p in st.session_state.menu_dinamico:
                            st.session_state.menu_dinamico[p]["stock"] = nuevo_st
                    # Mensaje discreto en consola o warning suave
                    st.toast("⚠️ Nota: El inventario se actualizará en la nube en breve debido a la alta demanda.", icon="⏳")
                
                usuario_email = st.session_state.user_info.get("email", "") if st.session_state.user_info else ""
                orden_creada = database.crear_orden(
                    db_path=None,
                    fecha_hora=fecha_actual,
                    nro_boleta=correlativo_sunat,
                    detalle_articulos=resumen_articulos_linea,
                    entrega=tipo_entrega_db,
                    metodo_pago=metodo_pago,
                    total=f"S/{total_con_delivery:.2f}",
                    usuario_email=usuario_email
                )

                if not orden_creada:
                    st.error("⚠️ No se pudo registrar la orden. Revise la conexión con Google Sheets.")
                    st.stop()

                # Fidelidad: si está logueado, sumar compra
                if st.session_state.user_info:
                    email_usuario = st.session_state.user_info.get("email")
                    if email_usuario:
                        # Si usó el cupón de bienvenida o premio, vamos a desactivarlo para que no lo vuelva a usar
                        if st.session_state.cupon_aplicado and (st.session_state.cupon_aplicado.startswith("BIENVENIDO-") or st.session_state.cupon_aplicado.startswith("PREMIO")):
                            database.actualizar_estado_cupon(st.session_state.cupon_aplicado, False)
                            
                        # Incrementar compra
                        nuevo_premio = database.incrementar_compra_usuario(email_usuario)
                        st.session_state.db_user = None
                        if nuevo_premio:
                            st.toast(f"¡Felicidades! Desbloqueaste un nuevo premio: {nuevo_premio}", icon="🎁")

                # Marcar mesa como OCUPADA al confirmar pedido (refuerzo)
                if st.session_state.get("tipo_servicio") == "salon" and st.session_state.get("mesa_seleccionada"):
                    try:
                        database.actualizar_estado_mesa(st.session_state.mesa_seleccionada, "ocupada")
                        st.cache_data.clear()
                    except Exception:
                        pass  # No bloquear la boleta si falla la mesa

                st.session_state.ultima_boleta_time = tiempo_actual_ts
                st.session_state.boleta_emitida = True
                st.session_state.numero_boleta = numero_boleta_actual
                st.session_state.correlativo_sunat = correlativo_sunat
                st.session_state.menu_dinamico = database.obtener_menu()
                st.session_state.historial_ordenes = database.obtener_ordenes()
                st.success("PAGO REALIZADO CORRECTAMENTE - Pedido registrado exitosamente")
                st.balloons()
                render_stepper(3)
                st.markdown("### 🧾 COMPROBANTE EMITIDO")
                
                if metodo_pago == "Tarjeta":
                    metodo_pago_txt = escapar_html(f"TARJETA (APROBADA)\nTitular:      {titular_tarjeta}\nNro. Tarjeta: ************{ultimos_digitos}")
                elif metodo_pago == "Yape":
                    metodo_pago_txt = "YAPE (PAGO ELECTRÓNICO)\nVuelto:       S/ 0.00 (Monto exacto)"
                else:
                    metodo_pago_txt = escapar_html(f"EFECTIVO\nEfectivo Recibido: S/{pago_usuario:.2f}\nVuelto:            S/{vuelto:.2f}")
                
                if os.path.exists(RUTA_HTML):
                    with open(RUTA_HTML, "r", encoding="utf-8") as archivo_html:
                        plantilla_contenido = archivo_html.read()
                    
                    html_final = plantilla_contenido\
                        .replace("{{ SERIE_BOLETA }}", escapar_html(correlativo_sunat))\
                        .replace("{{ FECHA_HORA }}", escapar_html(fecha_actual))\
                        .replace("{{ TIPO_ENTREGA }}", tipo_entrega_html)\
                        .replace("{{ METODO_PAGO }}", metodo_pago_txt)\
                        .replace("{{ DETALLE_PRODUCTOS }}", detalle_productos_txt.strip())\
                        .replace("{{ TOTAL_FINAL }}", f"{total_con_delivery:.2f}")
                    
                    components.html(html_final, height=850)

                else:
                    st.error("⚠️ Error: No se pudo encontrar 'boleta_plantilla.html'.")
                    
        if st.session_state.get("boleta_emitida", False):
            st.markdown("---")
            if st.session_state.get("tipo_servicio", "salon") == "delivery":
                st.markdown("""
                <div class="countdown-container">
                    <div class="countdown-time">35:00</div>
                    <div class="countdown-label">Tiempo estimado de entrega</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("### 📱 Enviar comprobante al negocio")
            link_wa = construir_mensaje_whatsapp(st.session_state.get('correlativo_sunat', 'B001-000000'), st.session_state.carrito, total_con_delivery, "Delivery" if tiene_delivery else "Local", st.session_state.cliente_nombre, st.session_state.cliente_telefono)
            st.markdown(f'<a href="{link_wa}" target="_blank" style="display:block; text-align:center; background:linear-gradient(135deg, #25d366, #1cbd55); color:white; padding:12px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:18px; margin-bottom:20px;">🟢 ENVIAR PEDIDO POR WHATSAPP</a>', unsafe_allow_html=True)
            
            st.markdown("### ⭐ Califica tu experiencia")
            calificacion = st.slider("¿Qué te pareció el servicio?", 1, 5, 5, help="1 es muy malo, 5 es excelente")
            comentario_cal = st.text_input("Déjanos un comentario (opcional):", key="comentario_cal")
            if st.button("Enviar calificación"):
                exito_cal = database.crear_calificacion(None, fecha_actual, st.session_state.get('correlativo_sunat', ''), calificacion, comentario_cal)
                if exito_cal:
                    st.success("¡Gracias por tu calificación!")
                    
        st.markdown("---")
        if st.button("⬅️ VOLVER AL CATÁLOGO", use_container_width=True, key="btn_volver_catalogo"):
            st.session_state.pedido_guardado = False
            st.session_state.boleta_emitida = False
            st.session_state.pantalla_actual = "catalogo"
            st.rerun()

        if st.session_state.pedido_guardado:
            if st.button("🔄 Crear una nueva orden", use_container_width=True, key="btn_nueva_orden_final"):
                st.session_state.carrito = []
                st.session_state.total_acumulado = 0.0
                st.session_state.pedido_guardado = False
                st.session_state.boleta_emitida = False
                st.session_state.pantalla_actual = "bienvenida"
                st.rerun()
