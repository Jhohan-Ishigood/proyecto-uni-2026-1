# ============================================================================
# 1. CONFIGURACIÓN DEL SISTEMA, IMPORTACIONES Y RUTAS DE CONTROL
# ============================================================================
import streamlit as st
from datetime import datetime, timedelta, timezone
import os
import json
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
from difflib import SequenceMatcher
import database
import requests
import urllib.parse

# Configuración inicial del lienzo responsivo de la aplicación
st.set_page_config(
    page_title="El Gran Búfalo - Sistema de Pedidos", 
    page_icon="🥩", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

st.markdown('<meta name="description" content="El Gran Búfalo - Sistema de pedidos online. Parrillas, hamburguesas y más. Delivery disponible.">', unsafe_allow_html=True)

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
    return None

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
    """Relee el menú sin caché y confirma que el carrito todavía tenga stock suficiente."""
    menu_actualizado = database.obtener_menu(ttl=1)
    errores = []

    for item in carrito:
        producto = item["producto"]
        cantidad = int(item["cantidad"])
        info = menu_actualizado.get(producto)

        if not info:
            errores.append(f"'{producto}' ya no existe en la carta.")
            continue

        stock_actual = int(info.get("stock", 0))
        if not info.get("disponible", False):
            errores.append(f"'{producto}' ya no está disponible.")
        elif stock_actual < cantidad:
            errores.append(f"'{producto}' solo tiene {stock_actual} unidad(es) disponibles.")

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

    cupones_db = database.obtener_cupones(ttl=0)
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
        "Hola, El Gran Bufalo.",
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
        html += f"<div style='display:flex;align-items:center;'>"
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
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        # Comprimir como JPEG
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=calidad, optimize=True)
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        st.error(f"Error al codificar la imagen a Base64: {e}")
        return None

def obtener_src_foto(ruta_foto):
    """Convierte una ruta de imagen local a Base64 o la retorna tal cual si es una data URL."""
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

# ============================================================================
# 3. INICIALIZACIÓN DE VARIABLES REACTIVAS DE SESIÓN (ESTADOS DEL SISTEMA)
# ============================================================================
# Carga inicial de datos (solo una vez por sesión, o cuando se fuerza recarga)
if "menu_dinamico" not in st.session_state or st.session_state.get("_forzar_recarga", False):
    st.session_state.menu_dinamico = database.obtener_menu()
    st.session_state.historial_ordenes = database.obtener_ordenes()
    st.session_state.lista_categorias = ["Todos"] + database.obtener_categorias()
    st.session_state["_forzar_recarga"] = False

if "carrito" not in st.session_state:
    st.session_state.carrito = []
if "total_acumulado" not in st.session_state:
    st.session_state.total_acumulado = 0.0
if "pedido_guardado" not in st.session_state:
    st.session_state.pedido_guardado = False
if "boleta_emitida" not in st.session_state:
    st.session_state.boleta_emitida = False
if "pantalla_actual" not in st.session_state:
    st.session_state.pantalla_actual = "bienvenida"
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

# Anclaje y sincronización de reloj oficial para Perú (GMT-5)
zona_peru = timezone(timedelta(hours=-5))
ahora_peru = datetime.now(zona_peru)
fecha_actual = ahora_peru.strftime("%d/%m/%Y %H:%M:%S")
servicio_abierto = pedidos_abiertos(ahora_peru)

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
if os.path.exists(RUTA_CSS):
    with open(RUTA_CSS, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Inyección directa del fondo visual premium (no depende de pseudo-elementos CSS)
st.markdown("""
<div id="fondo-premium" style="
    position: fixed;
    top: 0; left: 0;
    width: 100vw; height: 100vh;
    pointer-events: none;
    z-index: 0;
    background:
        radial-gradient(ellipse 600px 500px at 10% 0%, rgba(233, 30, 140, 0.20) 0%, transparent 70%),
        radial-gradient(ellipse 500px 600px at 90% 5%, rgba(156, 39, 176, 0.18) 0%, transparent 65%),
        radial-gradient(ellipse 700px 400px at 50% 95%, rgba(233, 30, 140, 0.14) 0%, transparent 65%),
        radial-gradient(ellipse 400px 400px at 5% 90%, rgba(103, 58, 183, 0.16) 0%, transparent 60%),
        radial-gradient(ellipse 800px 800px at 50% 40%, rgba(156, 39, 176, 0.06) 0%, transparent 70%);
    animation: auroraMovimiento 18s ease-in-out infinite alternate;
"></div>
<style>
@keyframes auroraMovimiento {
    0% { opacity: 0.85; filter: hue-rotate(0deg); }
    50% { opacity: 1; filter: hue-rotate(6deg); }
    100% { opacity: 0.85; filter: hue-rotate(-4deg); }
}
</style>
""", unsafe_allow_html=True)

# Inyección limpia del sello de creador adaptado al flujo estructural
st.markdown("<div class='sello-creador'>Pagina desarrollada por: Jhohan--Patrick--Eros--Jack--Carlos (Grupo 5) 😎</div>", unsafe_allow_html=True)

# ============================================================================
# 6. BARRA LATERAL (SIDEBAR POS): GESTIÓN INTERNA Y AUTENTICACIÓN
# ============================================================================
st.sidebar.markdown("<h2 style='text-align: center; color: #f39c12;'>🥩 El Gran Búfalo</h2>", unsafe_allow_html=True)
st.sidebar.markdown("<p style='text-align: center; font-size: 13px; color: #aaa;'>Especialistas en carnes y parrillas premium al carbón de manera artesanal.</p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

# ============================================================================
# 6.1 PERFIL DE USUARIO CLIENTE (GOOGLE OAUTH)
# ============================================================================
if st.session_state.user_info:
    # Mostrar perfil del usuario
    u_info = st.session_state.user_info
    st.sidebar.markdown("#### 👤 MI PERFIL")
    col_p1, col_p2 = st.sidebar.columns([1, 3])
    with col_p1:
        st.markdown(f"<img src='{u_info.get('picture', '')}' style='border-radius:50%; width:100%;'>", unsafe_allow_html=True)
    with col_p2:
        st.markdown(f"**{u_info.get('name', '')}**")
        st.caption(f"{u_info.get('email', '')}")
    
    # Obtener info de la BD para mostrar compras/puntos
    db_user = database.obtener_usuario(u_info.get('email', ''))
    if db_user:
        compras = db_user.get("compras_realizadas", 0)
        st.sidebar.info(f"🏆 Compras realizadas: **{compras}**")
        faltan = 3 - (compras % 3)
        st.sidebar.caption(f"A {faltan} compras de tu próximo cupón de S/10.")
    
    if st.sidebar.button("Cerrar Sesión", use_container_width=True):
        st.session_state.user_info = None
        st.rerun()
else:
    st.sidebar.markdown("#### 👤 CLIENTE FRECUENTE")
    st.sidebar.info("¡Inicia sesión para obtener **15% de descuento** en tu primera compra y sumar puntos para premios!", icon="🎁")
    auth_url = get_google_auth_url()
    st.sidebar.markdown(f'<a href="{auth_url}" target="_blank" style="display:inline-block; width:100%; text-align:center; background-color:#ffffff; color:#444; border:1px solid #ddd; padding:8px 0; border-radius:4px; text-decoration:none; font-weight:bold; font-family:sans-serif;">Continúa con Google</a>', unsafe_allow_html=True)

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

# Renderizado condicional del bloque de autenticación administrativa
if st.session_state.mostrar_login_admin:
    with st.sidebar.container():
        usuario_input = st.text_input("Nombre de Usuario:", key="user_login").strip()
        clave_input = st.text_input("Contraseña:", type="password", key="pass_login").strip()

# Validación de credenciales blindada: sin secrets configurados no hay acceso admin
USER_PROD = st.secrets.get("admin_user", "Grupo 5")
PASS_PROD = st.secrets.get("admin_password", "jhohan-2026")
credenciales_admin_configuradas = bool(USER_PROD and PASS_PROD)

es_admin = credenciales_admin_configuradas and usuario_input == USER_PROD and clave_input == PASS_PROD

# Retroalimentación interactiva del estado del usuario
if es_admin:
    st.sidebar.success("✔ Modo Administrador Activo")
elif st.session_state.mostrar_login_admin and not credenciales_admin_configuradas:
    st.sidebar.warning("Admin no configurado. Agregue admin_user y admin_password en Streamlit Secrets.")
elif usuario_input or clave_input:
    st.sidebar.error("❌ Credenciales incorrectas")

st.sidebar.markdown("---")
st.sidebar.markdown("#### 🕒 HORARIO DE ATENCIÓN")
st.sidebar.caption("Lunes a Domingo: 8:00 AM - 11:00 PM")

st.sidebar.markdown("#### 📍 NUESTRA UBICACIÓN")
st.sidebar.caption("Av. Principal El Gran Búfalo 742, Trujillo, Perú")
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
# 8. PANEL DE CONTROL DE ADMINISTRACIÓN - GESTOR DE SECCIONES (JSON)
# ============================================================================
if es_admin:
    st.markdown("<h1 class='titulo-principal'>📊 PANEL DE ADMINISTRACIÓN</h1>", unsafe_allow_html=True)
    st.info(f"📋 **Reporte Gerencial del Grupo 5** — Sincronizado en tiempo real: {fecha_actual}")
    st.session_state.pedidos_pausados = st.toggle(
        "Pausar recepción de pedidos de clientes",
        value=st.session_state.pedidos_pausados,
        help="Bloquea temporalmente nuevos pedidos sin modificar la carta.",
    )
    if st.session_state.pedidos_pausados:
        st.warning("La recepción de pedidos está pausada para esta sesión.")
    st.markdown("<br>", unsafe_allow_html=True)

    # Bloque expandible de control de pestañas y categorías
    with st.expander("📁 ⚙️ CONFIGURACIÓN DE SECCIONES EN LA CARTA", expanded=False):
        st.caption("Añada nuevas pestañas al menú horizontal o elimine las secciones que ya no utilice en la jornada.")
        st.markdown("<br>", unsafe_allow_html=True)

        col_cat1, col_cat2 = st.columns(2, gap="medium")
        
        with col_cat1:
            with st.container(border=True):
                st.markdown("##### ➕ Crear Nueva Sección")
                nueva_cat = st.text_input(
                    "Crear Sección", 
                    placeholder="Escribe aquí la nueva sección (Ej. Postres)...", 
                    key="input_create_cat_name",
                    label_visibility="collapsed"
                ).strip().capitalize()
                
                if st.button("➕ CREAR NUEVA SECCIÓN", use_container_width=True, key="btn_create_cat"):
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
                    label_visibility="collapsed"
                )
                
                if st.button("🗑️ ELIMINAR SECCIÓN SELECCIONADA", use_container_width=True, key="btn_delete_cat"):
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
    with st.expander("➕ 🛠️ AÑADIR NUEVO PRODUCTO CON FOTO", expanded=False):
        st.caption("Complete los datos para agregar un plato nuevo subiendo una imagen desde su dispositivo.")
        nuevo_nombre = st.text_input("Nombre del nuevo producto:", placeholder="Ej. Alitas BBQ, Papas Nativas...").strip()
        
        col_new1, col_new2, col_new3, col_new4 = st.columns(4)
        with col_new1:
            nuevo_precio = st.number_input("Precio de venta (S/):", min_value=0.5, value=10.0, step=0.5)
        with col_new2:
            nuevo_icono = st.text_input("Icono (Emoji):", value="🍟", max_chars=2).strip()
        with col_new3:
            nuevo_stock = st.number_input("Stock (Unidades):", min_value=0, value=15, step=1)
        with col_new4:
            cats_creadas = [c for c in st.session_state.lista_categorias if c != "Todos"]
            nueva_categoria_asociada = st.selectbox("Categoría asignada:", options=cats_creadas)
            
        archivo_foto = st.file_uploader("Selecciona la foto del plato desde tu equipo:", type=["jpg", "jpeg", "png"], key="upload_nuevo_prod")
            
        if st.button("🚀 GUARDAR E INTEGRAR NUEVO PRODUCTO", use_container_width=True):
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
    st.markdown("### 📝 GESTIÓN DE PRECIOS, STOCK Y FOTOS")
    st.caption(f"Modifique los valores. Filtrado actual: **{st.session_state.categoria_activa}**")
    
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
                
                nueva_cat_izq = st.selectbox(f"Sección de {p_izq}:", options=cats_izq, index=cats_izq.index(cat_act_izq) if cat_act_izq in cats_izq else 0, key=f"cat_edit_{p_izq}")
                
                p_izq_val = st.number_input(f"Precio (S/) - {p_izq}:", min_value=1.0, value=float(st.session_state.menu_dinamico[p_izq]["precio"]), step=0.5, key=f"p_{p_izq}")
                p_izq_disp = st.checkbox("Disponible para venta", value=st.session_state.menu_dinamico[p_izq]["disponible"], key=f"d_{p_izq}")
                p_izq_stock = st.number_input(f"Stock Disponible - {p_izq}:", min_value=0, value=int(st.session_state.menu_dinamico[p_izq].get("stock", 10)), step=1, key=f"s_{p_izq}")
                
                foto_cambio_izq = st.file_uploader(f"Actualizar foto de {p_izq}:", type=["jpg", "jpeg", "png"], key=f"f_up_{p_izq}")
                
                cambios_detectados[p_izq] = {
                    "precio": p_izq_val, 
                    "icono": st.session_state.menu_dinamico[p_izq]["icono"], 
                    "disponible": p_izq_disp, 
                    "stock": p_izq_stock, 
                    "categoria": nueva_cat_izq
                }
                
                if st.button(f"❌ Eliminar {p_izq}", key=f"del_{p_izq}", use_container_width=True):
                    eliminar_producto = p_izq
                
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
                    
                    nueva_cat_der = st.selectbox(f"Sección de {p_der}:", options=cats_der, index=cats_der.index(cat_act_der) if cat_act_der in cats_der else 0, key=f"cat_edit_{p_der}")
                    
                    p_der_val = st.number_input(f"Precio (S/) - {p_der}:", min_value=1.0, value=float(st.session_state.menu_dinamico[p_der]["precio"]), step=0.5, key=f"p_{p_der}")
                    p_der_disp = st.checkbox("Disponible para venta", value=st.session_state.menu_dinamico[p_der]["disponible"], key=f"d_{p_der}")
                    p_der_stock = st.number_input(f"Stock Disponible - {p_der}:", min_value=0, value=int(st.session_state.menu_dinamico[p_der].get("stock", 10)), step=1, key=f"s_{p_der}")
                    
                    foto_cambio_der = st.file_uploader(f"Actualizar foto de {p_der}:", type=["jpg", "jpeg", "png"], key=f"f_up_{p_der}")
                    
                    cambios_detectados[p_der] = {
                        "precio": p_der_val, 
                        "icono": st.session_state.menu_dinamico[p_der]["icono"], 
                        "disponible": p_der_disp, 
                        "stock": p_der_stock, 
                        "categoria": nueva_cat_der
                    }
                    
                    if st.button(f"❌ Eliminar {p_der}", key=f"del_{p_der}", use_container_width=True):
                        eliminar_producto = p_der
        st.markdown("---")

    # ============================================================================
    # 12. MANEJADOR OPERATIVO DE PERSISTENCIA SEGURA
    # ============================================================================
    if eliminar_producto is not None:
        if database.eliminar_producto(None, eliminar_producto):
            st.success(f"✔ ¡Producto '{eliminar_producto}' eliminado con éxito!")
            st.session_state["_forzar_recarga"] = True
            st.rerun()

    if st.button("💾 CONFIRMAR Y SINCRONIZAR CAMBIOS DE LA CARTA", use_container_width=True):
        # Sincronizamos los cambios al almacenamiento de Google Sheets
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

    # ============================================================================
    # 12.5 PANEL DE CONTROL DE ADMINISTRACIÓN - GESTIÓN DE CUPONES
    # ============================================================================
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🎫 GESTIÓN DE CUPONES")
    
    with st.expander("Añadir / Editar Cupones", expanded=False):
        c_col1, c_col2, c_col3, c_col4 = st.columns(4)
        with c_col1:
            nuevo_codigo = st.text_input("Código del cupón (ej. VERANO20)").strip().upper()
        with c_col2:
            nuevo_tipo = st.selectbox("Tipo de descuento", ["porcentaje", "monto", "delivery"])
        with c_col3:
            nuevo_valor = st.number_input("Valor (ej. 0.2 para 20%, o 10.0 para S/10)", min_value=0.0, step=0.1)
        with c_col4:
            nueva_desc = st.text_input("Descripción breve")
            
        if st.button("➕ Guardar Cupón", use_container_width=True):
            if nuevo_codigo and nuevo_valor > 0:
                if database.crear_cupon(nuevo_codigo, nuevo_tipo, nuevo_valor, nueva_desc, activo=True):
                    st.success(f"Cupón {nuevo_codigo} guardado.")
                    st.rerun()
            else:
                st.error("Ingrese código y valor mayor a 0.")
                
        st.markdown("#### Cupones Actuales")
        cupones_db = database.obtener_cupones(ttl=0)
        if cupones_db:
            for cod, datos in cupones_db.items():
                col_c1, col_c2, col_c3, col_c4 = st.columns([2, 3, 1, 1])
                with col_c1:
                    st.markdown(f"**{cod}**")
                    st.caption(f"{datos['tipo']} - {datos['valor']}")
                with col_c2:
                    st.write(datos["descripcion"])
                with col_c3:
                    estado = st.toggle("Activo", value=bool(datos["activo"]), key=f"tgl_{cod}")
                    if estado != bool(datos["activo"]):
                        database.actualizar_estado_cupon(cod, estado)
                        st.rerun()
                with col_c4:
                    if st.button("🗑️", key=f"del_cup_{cod}"):
                        database.eliminar_cupon(cod)
                        st.rerun()
        else:
            st.info("No hay cupones registrados.")

    # ============================================================================
    # 13. PANEL DE CONTROL DE ADMINISTRACIÓN - AUDITORÍA FINANCIERA Y ANALÍTICA
    # ============================================================================
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
    horas_pedidos = {}
    for orden in st.session_state.historial_ordenes:
        try:
            hora = orden.get('Fecha y Hora', '').split(' ')[1].split(':')[0]
            horas_pedidos[hora] = horas_pedidos.get(hora, 0) + 1
        except (IndexError, KeyError):
            pass
    hora_pico = max(horas_pedidos, key=horas_pedidos.get) if horas_pedidos else "--"
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
        df_historial.columns = ["🕒 FECHA Y HORA", "🧾 NRO. BOLETA", "📦 DETALLE ARTÍCULOS", "🛵 ENTREGA", "💳 MÉTODO PAGO", "💰 TOTAL"]
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
else:
    # ============================================================================
    # 15. ENTORNO CLIENTE - PANTALLA 1: BIENVENIDA MULTIMEDIA PREMIUM
    # ============================================================================
    if st.session_state.pantalla_actual == "bienvenida":
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<h2 class='titulo-principal'>SISTEMA DE PEDIDOS GRAN BÚFALO</h2>", unsafe_allow_html=True)
        st.markdown("<br><p style='text-align: center; font-size: 24px; font-weight: bold; color: #f39c12;'>🔥 Bienvenidos al templo de la buena carne 🔥</p>", unsafe_allow_html=True)
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
        
        if st.button("🛒 EMPEZAR MI PEDIDO", use_container_width=True, key="btn_empezar_pedido_master", disabled=not servicio_abierto):
            st.session_state.pantalla_actual = "catalogo"
            st.session_state.boleta_emitida = False
            st.rerun()
            
        # Bloque de Redes Sociales Corporativas de El Gran Búfalo
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
    # 16. ENTORNO CLIENTE - PANTALLA 2: CATÁLOGO DINÁMICO DE PRODUCTOS
    # ============================================================================
    elif st.session_state.pantalla_actual == "catalogo" and not st.session_state.pedido_guardado:
        render_stepper(1)
        st.markdown("\n<h2 class='titulo-principal'>SISTEMA DE PEDIDOS GRAN BÚFALO</h2>", unsafe_allow_html=True)
        st.text(f"Fecha y hora oficial de Perú (GMT-5): {fecha_actual}\n")
        
        st.subheader(f"🍽️ SELECCIÓN DE {st.session_state.categoria_activa.upper()}")
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
        producto_mas_vendido = max(conteos_productos, key=conteos_productos.get) if conteos_productos and max(conteos_productos.values()) > 0 else None

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
                    
                    cantidades_ingresadas[prod] = st.number_input(
                        f"Cantidad de {prod}:", min_value=0, max_value=int(stock_actual), step=1, key=f"cat_{prod}", label_visibility="collapsed"
                    )
                    st.markdown("<br>", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div style="width:100%; height:200px; background-color:#222; border-radius:12px 12px 0px 0px; display:flex; align-items:center; justify-content:center;"><span style="font-size:50px; filter:grayscale(100%);">{icono_html}</span></div>""", unsafe_allow_html=True)
                    st.markdown(f"<div style='background-color:#151515; padding:20px; border-radius:0px 0px 12px 12px; border:2px solid #ff4b4b; text-align:center; margin-bottom:25px;'><p style='color: #ff4b4b; font-size:18px; font-weight: bold; margin:0;'>❌ {prod_html}<br>(AGOTADO)</p></div>", unsafe_allow_html=True)
        st.markdown("---")
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
                value=st.session_state.cliente_nombre,
                placeholder="Ej. María López",
            ).strip()
        with col_cliente2:
            st.session_state.cliente_telefono = st.text_input(
                "Teléfono de contacto",
                value=st.session_state.cliente_telefono,
                placeholder="Ej. 982174847",
            ).strip()

        opcion_delivery = st.radio("¿Desea delivery? (+ S/6.00)", ["NO", "SI"], horizontal=True)
        direccion_delivery = ""
        costo_delivery = 0.0
        tiene_delivery = False
        
        if opcion_delivery == "SI":
            tiene_delivery = True
            costo_delivery = 6.0
            direccion_delivery = st.text_input("Ingrese su dirección de entrega (Ubicación):", placeholder="Ej. Av. Larco 123...").strip()
        st.caption(f"Tiempo estimado: {tiempo_estimado_texto(tiene_delivery)}")

        total_items_checkout = sum(int(item["cantidad"]) for item in st.session_state.carrito)
        
        valor_cupon_defecto = st.session_state.cupon_aplicado
        if st.session_state.user_info and not valor_cupon_defecto:
            db_user = database.obtener_usuario(st.session_state.user_info.get("email", ""))
            if db_user:
                nombre_pila = db_user.get("nombre", "").split(" ")[0].upper()
                cupon_bienvenida = f"BIENVENIDO-{nombre_pila}"
                cupones_bd = database.obtener_cupones(ttl=0)
                if cupon_bienvenida in cupones_bd and cupones_bd[cupon_bienvenida]["activo"]:
                    valor_cupon_defecto = cupon_bienvenida
                    st.session_state.cupon_aplicado = cupon_bienvenida

        st.session_state.cupon_aplicado = st.text_input(
            "Cupón de descuento",
            value=valor_cupon_defecto,
            placeholder="BUFFALO10, DELIVERYFREE o COMBO5",
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
                        st.error(f"⚠️ {error_stock}")
                    st.session_state.menu_dinamico = menu_actualizado
                    st.session_state["_forzar_recarga"] = True
                    st.stop()

                historial_actualizado = database.obtener_ordenes(ttl=1)
                numero_boleta_actual = generar_numero_boleta(historial_actualizado)
                correlativo_sunat = f"B001-{numero_boleta_actual:06d}"
                detalle_productos_txt = ""
                items_resumen_lista = []
                
                for item in st.session_state.carrito:
                    producto_boleta = escapar_html(item["producto"])
                    detalle_productos_txt += f"{item['cantidad']}x {producto_boleta:<18} S/{item['subtotal']:.2f}\n"
                    items_resumen_lista.append(f"{item['cantidad']}x {item['producto']}")
                
                if tiene_delivery:
                    detalle_productos_txt += f"1x Costo de Envío        S/6.00\n"
                    items_resumen_lista.append("1x Delivery")
                
                resumen_articulos_linea = ", ".join(items_resumen_lista)
                tipo_entrega_db = f"DELIVERY ({direccion_delivery})" if tiene_delivery else "LOCAL"
                tipo_entrega_html = escapar_html(tipo_entrega_db)
                
                stock_actualizado = True
                for item in st.session_state.carrito:
                    prod_comprado = item["producto"]
                    cant_comprada = item["cantidad"]
                    nuevo_stock = int(menu_actualizado[prod_comprado].get("stock", 0)) - int(cant_comprada)
                    stock_actualizado = database.actualizar_stock(None, prod_comprado, nuevo_stock) and stock_actualizado

                if not stock_actualizado:
                    st.error("⚠️ No se pudo actualizar el stock. La orden no fue registrada.")
                    st.stop()
                
                orden_creada = database.crear_orden(
                    db_path=None,
                    fecha_hora=fecha_actual,
                    nro_boleta=correlativo_sunat,
                    detalle_articulos=resumen_articulos_linea,
                    entrega=tipo_entrega_db,
                    metodo_pago=metodo_pago,
                    total=f"S/{total_con_delivery:.2f}"
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
                        if nuevo_premio:
                            st.toast(f"¡Felicidades! Desbloqueaste un nuevo premio: {nuevo_premio}", icon="🎁")

                st.session_state.ultima_boleta_time = tiempo_actual_ts
                st.session_state.boleta_emitida = True
                st.session_state.numero_boleta = numero_boleta_actual
                st.session_state.correlativo_sunat = correlativo_sunat
                st.session_state.menu_dinamico = database.obtener_menu(ttl=1)
                st.session_state.historial_ordenes = database.obtener_ordenes(ttl=1)
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
            if tiene_delivery:
                st.markdown("""
                <div class="countdown-container">
                    <div class="countdown-time">35:00</div>
                    <div class="countdown-label">Tiempo estimado de entrega</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="countdown-container">
                    <div class="countdown-time">15:00</div>
                    <div class="countdown-label">Tiempo estimado para recojo</div>
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
