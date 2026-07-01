"""Script de diagnóstico para Google Sheets connection."""
import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Diagnóstico Google Sheets")

st.title("🔍 Diagnóstico de conexión a Google Sheets")

spreadsheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
client_email = st.secrets["connections"]["gsheets"]["client_email"]

st.markdown(f"**Spreadsheet:** `{spreadsheet_url}`")
st.markdown(f"**Service account:** `{client_email}`")

st.markdown("---")
st.subheader("Paso 1: Probar conexión")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    st.success("✅ Conexión establecida con `st.connection`")
except Exception as e:
    st.error(f"❌ Error al conectar: {e}")
    st.stop()

st.subheader("Paso 2: Listar hojas disponibles")

# Intentar leer algunas hojas comunes
hojas = ["productos", "categorias", "ordenes", "menu"]
for hoja in hojas:
    try:
        df = conn.read(worksheet=hoja, ttl=0)
        st.success(f"✅ Hoja '{hoja}' encontrada — {len(df)} filas, columnas: {list(df.columns)}")
        if hoja == "productos" and not df.empty:
            st.dataframe(df.head(20), use_container_width=True)
    except Exception as e:
        st.warning(f"⚠️ Hoja '{hoja}': {e}")

st.subheader("Paso 3: Verificar columnas de 'productos'")

try:
    df = conn.read(worksheet="productos", ttl=0)
    if not df.empty:
        st.markdown(f"**{len(df)} productos encontrados**")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("La hoja 'productos' existe pero está vacía")
except Exception as e:
    st.error(f"❌ Error leyendo 'productos': {e}")

st.markdown("---")
st.info("Si ves errores arriba, comparte esta pantalla para diagnosticar.")
