
import openpyxl
import streamlit as st
import pandas as pd
import numpy as np
import os

# 1. Configuración básica
st.set_page_config(page_title="Cotizador de Renovaciones", page_icon="🛡️", layout="wide")
st.title("🛡️ Herramienta de Tarifación para Renovaciones")

# --- NUEVO: SISTEMA DE AUTO-GUARDADO Y RECUPERACIÓN ---
archivos_respaldo = {
    'df_polizas': 'backup_polizas.pkl',
    'df_curva': 'backup_curva.pkl',
    'df_siniestros': 'backup_siniestros.pkl',
    'datos_procesados': 'backup_procesados.pkl'
}

# 2. Inicializar Memoria (Leyendo del disco si existen respaldos)
for key, archivo in archivos_respaldo.items():
    if key not in st.session_state:
        # Si el archivo de respaldo existe físicamente, lo cargamos
        if os.path.exists(archivo):
            st.session_state[key] = pd.read_pickle(archivo)
        else:
            st.session_state[key] = None


# 3. Función de procesamiento principal
@st.cache_data(show_spinner=False)
def procesar_datos(polizas_raw, curva_raw, siniestros_raw):
    polizas = polizas_raw.copy()
    curva_riesgo = curva_raw.copy()
    siniestros = siniestros_raw.copy()
    
    curva_siniestros = pd.merge(siniestros, polizas, on='Poliza_Id', how='left')
    TPR = curva_siniestros["Valor del Siniestro"].mean() / (curva_siniestros["VA_Ajuste_Prueba"].mean() * 100)

    polizas_riesgo = pd.merge(polizas, curva_riesgo, left_on=['Amparo_Id', 'Edad_Cliente'], right_on=['Amparo_ID', 'Edad'], how='inner')
    polizas_riesgo["PPRC"] = polizas_riesgo["VA_Ajuste_Prueba"] * polizas_riesgo["Tasa"]
    polizas_riesgo["TCPC"] = polizas_riesgo["Tasa"] / (1 - 0.4)
    polizas_riesgo['VA_Solo_Vida'] = np.where(polizas_riesgo['Amparo_Desc'].str.startswith('VIDA', na=False), polizas_riesgo['VA_Ajuste_Prueba'], 0)

    tasa_unica_poliza = polizas_riesgo.groupby(['Poliza_Id'])[['PPRC', "VA_Solo_Vida"]].sum().reset_index()
    tasa_unica_poliza = tasa_unica_poliza.rename(columns={'PPRC': 'Prima por Cobertura'})
    tasa_unica_poliza["Tasa Unica pura de riesgo"] = tasa_unica_poliza["Prima por Cobertura"] / tasa_unica_poliza["VA_Solo_Vida"]
    tasa_unica_poliza["Tasa Unica comercial"] = tasa_unica_poliza["Tasa Unica pura de riesgo"] / (1 - 0.4)

    siniestros["n"] = siniestros.groupby(['Poliza_Id'])["Poliza_Id"].transform('count')
    siniestros['Valor_Calculo'] = np.where(siniestros['Valor del Siniestro'] > 2350, 2350, siniestros['Valor del Siniestro'])
    siniestros["varianza_por_cliente"] = siniestros.groupby('Poliza_Id')['Valor_Calculo'].transform('var', ddof=1).fillna(0)
    siniestros["media_por_cliente"] = siniestros.groupby('Poliza_Id')['Valor_Calculo'].transform('mean').fillna(0)

    siniestros_gb = siniestros.groupby(['Poliza_Id']).agg({
        'Valor del Siniestro': 'mean', 'n': 'mean', 'varianza_por_cliente': 'mean', 'media_por_cliente': 'mean'
    }).reset_index()

    curva_siniestros["Valor_Calculo"] = curva_siniestros["Valor del Siniestro"].clip(upper=181418.13)
    siniestros_gb_ = curva_siniestros.groupby('Poliza_Id')['Valor_Calculo'].agg(['mean', 'var']).fillna(0)

    EPV = siniestros_gb_['var'].mean()
    VHM = siniestros_gb_['mean'].var(ddof=1)
    K_nuevo = EPV / VHM if VHM != 0 else 0

    siniestros_gb["K"] = K_nuevo
    siniestros_gb["Z"] = (siniestros_gb["n"] / (siniestros_gb["n"] + siniestros_gb["K"]))

    tasa_unica_poliza = pd.merge(tasa_unica_poliza, siniestros_gb[['Poliza_Id', 'Z']], on='Poliza_Id', how='left')
    tasa_unica_poliza["Z"] = tasa_unica_poliza["Z"].fillna(0)
    tasa_unica_poliza["tasa_cred"] = (tasa_unica_poliza["Z"] * tasa_unica_poliza["Tasa Unica pura de riesgo"]) + ((1 - tasa_unica_poliza["Z"]) * TPR)
    tasa_unica_poliza["prima_recomendada"] = tasa_unica_poliza["tasa_cred"] * tasa_unica_poliza["VA_Solo_Vida"]

    return tasa_unica_poliza


# 4. BARRA LATERAL: Gestión Modular de Datos
st.sidebar.header("📂 1. Gestión de Bases de Datos")

estado_p = "🟢" if st.session_state['df_polizas'] is not None else "🔴"
estado_c = "🟢" if st.session_state['df_curva'] is not None else "🔴"
estado_s = "🟢" if st.session_state['df_siniestros'] is not None else "🔴"
st.sidebar.markdown(f"{estado_p} Pólizas | {estado_c} Curva | {estado_s} Siniestros")
st.sidebar.divider()

# A. Actualizar Pólizas
with st.sidebar.expander("📄 Cargar / Actualizar Pólizas"):
    file_polizas = st.file_uploader("Archivo de Pólizas (.txt, .csv)", type=['txt', 'csv'], key="up_polizas")
    modo_carga = st.radio("Acción a realizar:", ["Reemplazar toda la base", "Actualizar / Agregar específicas"])
    
    if st.button("Aplicar Pólizas") and file_polizas:
        df_nuevo = pd.read_csv(file_polizas, sep='|', decimal=",")
        
        if modo_carga == "Reemplazar toda la base" or st.session_state['df_polizas'] is None:
            st.session_state['df_polizas'] = df_nuevo
        else:
            ids_nuevos = df_nuevo['Poliza_Id'].unique()
            df_actual = st.session_state['df_polizas']
            df_actual = df_actual[~df_actual['Poliza_Id'].isin(ids_nuevos)]
            st.session_state['df_polizas'] = pd.concat([df_actual, df_nuevo], ignore_index=True)
            
        # GUARDAR EN DISCO FÍSICO
        st.session_state['df_polizas'].to_pickle(archivos_respaldo['df_polizas'])
        st.success("Base de pólizas guardada correctamente.")

# B. Actualizar Curva
with st.sidebar.expander("📈 Cargar / Actualizar Curva de Riesgo"):
    file_curva = st.file_uploader("Archivo Curva (.xlsx)", type=['xlsx'], key="up_curva")
    if st.button("Aplicar Curva") and file_curva:
        st.session_state['df_curva'] = pd.read_excel(file_curva)
        st.session_state['df_curva'].to_pickle(archivos_respaldo['df_curva']) # Guardar
        st.success("Curva de riesgo guardada.")

# C. Actualizar Siniestros
with st.sidebar.expander("💥 Cargar / Actualizar Siniestros"):
    file_siniestros = st.file_uploader("Archivo Siniestros (.xlsx)", type=['xlsx'], key="up_siniestros")
    if st.button("Aplicar Siniestros") and file_siniestros:
        st.session_state['df_siniestros'] = pd.read_excel(file_siniestros)
        st.session_state['df_siniestros'].to_pickle(archivos_respaldo['df_siniestros']) # Guardar
        st.success("Siniestros históricos guardados.")

st.sidebar.divider()

# Botón Maestro de Cálculo
if st.session_state['df_polizas'] is not None and st.session_state['df_curva'] is not None and st.session_state['df_siniestros'] is not None:
    if st.sidebar.button("⚙️ Procesar y Calcular Tarifas", type="primary"):
        with st.spinner("Ejecutando modelos de credibilidad..."):
            try:
                df_final = procesar_datos(
                    st.session_state['df_polizas'], 
                    st.session_state['df_curva'], 
                    st.session_state['df_siniestros']
                )
                st.session_state['datos_procesados'] = df_final
                # GUARDAR RESULTADOS FINALES EN DISCO
                df_final.to_pickle(archivos_respaldo['datos_procesados'])
                st.sidebar.success("✅ Cálculos procesados y guardados.")
            except Exception as e:
                st.sidebar.error(f"Error al calcular: {e}")

# Botón para borrar todos los datos si se necesita empezar de cero
if st.sidebar.button("🗑️ Borrar toda la base de datos"):
    for key, archivo in archivos_respaldo.items():
        st.session_state[key] = None
        if os.path.exists(archivo):
            os.remove(archivo)
    st.rerun()

# 5. PANTALLA PRINCIPAL: Buscador y Resultados
if st.session_state['datos_procesados'] is not None:
    df_resultados = st.session_state['datos_procesados']
    
    st.subheader("🔍 2. Consultar Póliza")
    
    col_busqueda1, col_busqueda2 = st.columns(2)
    with col_busqueda1:
        busqueda_texto = st.text_input("Buscar por ID de Póliza (Escriba y presione Enter):", placeholder="Ej: 109553448")
    with col_busqueda2:
        lista_polizas = df_resultados['Poliza_Id'].astype(str).unique()
        busqueda_lista = st.selectbox("O seleccione de la lista:", [""] + list(lista_polizas))

    poliza_seleccionada = busqueda_texto if busqueda_texto != "" else busqueda_lista

    if poliza_seleccionada:
        if poliza_seleccionada in lista_polizas:
            datos_poliza = df_resultados[df_resultados['Poliza_Id'].astype(str) == poliza_seleccionada].iloc[0]

            st.header(f"Resultados para la Póliza: `{poliza_seleccionada}`")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(label="Factor Credibilidad (Z)", value=f"{datos_poliza['Z'] * 100:.2f}%")
            with col2:
                st.metric(label="Tasa Pura de Riesgo (TPR)", value=f"{datos_poliza['Tasa Unica pura de riesgo']:.4f}")
            with col3:
                diferencia_tasa = datos_poliza['tasa_cred'] - datos_poliza['Tasa Unica pura de riesgo']
                st.metric(label="Tasa Credibilizada", value=f"{datos_poliza['tasa_cred']:.4f}", 
                          delta=f"{diferencia_tasa:.4f} vs Pura", delta_color="inverse")
            with col4:
                st.metric(label="Tasa Comercial Unica", value=f"{datos_poliza['Tasa Unica comercial']:.4f}")

            st.divider()

            st.subheader("Comparativo Financiero")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.info(f"**Valor Asegurado (Solo Vida):**\n\n${datos_poliza['VA_Solo_Vida']:,.2f}")
            with col_b:
                st.warning(f"**Prima Actual (Por Cobertura):**\n\n${datos_poliza['Prima por Cobertura']:,.2f}")
            with col_c:
                st.success(f"**PRIMA RECOMENDADA NUEVA:**\n\n${datos_poliza['prima_recomendada']:,.2f}")

            with st.expander("Ver tabla completa de la póliza (Detalles crudos)"):
                st.dataframe(pd.DataFrame(datos_poliza).T, use_container_width=True)
        else:
            st.error(f"❌ La póliza '{poliza_seleccionada}' no se encuentra en la base de datos actual.")
else:
    st.info("👈 Sube los archivos en la barra lateral y presiona 'Procesar y Calcular Tarifas' para comenzar.")
    
import google.generativeai as genai
from docx import Document
import io

# ... (Tu código previo de cálculos y st.metric) ...

st.divider()
st.subheader("🤖 Asistente de Renovación IA")

prima_anterior = datos_poliza['Prima por Cobertura']
prima_nueva = datos_poliza['prima_recomendada']
variacion_pct = ((prima_nueva - prima_anterior) / prima_anterior) * 100 if prima_anterior > 0 else 0

st.info(f"Variación de la prima: **{variacion_pct:,.2f}%**")

# 1. Filtro estricto para aumentos
umbral_atipico = st.slider("Generar alerta si el aumento supera el (%):", 0, 100, 20)
es_atipica = variacion_pct > umbral_atipico

if es_atipica:
    st.warning("⚠️ Esta póliza presenta un incremento atípico. Se sugiere generar la carta de renovación.")

if st.button("✨ Generar Carta al Cliente con IA"):
    if not API_KEY:
        st.error("Falta la API Key de Gemini.")
    else:
        with st.spinner("Redactando propuesta comercial..."):
            
            prompt = f"""
            Actúa como un suscriptor de seguros experto y empático.
            Redacta UNA carta formal dirigida al cliente de la póliza {poliza_seleccionada}.
            
            Contexto:
            - Valor Asegurado: ${datos_poliza['VA_Solo_Vida']:,.2f}
            - Prima Anterior: ${prima_anterior:,.2f}
            - Prima Nueva Recomendada: ${prima_nueva:,.2f}
            
            Instrucciones:
            Justifica suavemente el incremento de la prima mencionando el ajuste por riesgo y las condiciones macroeconómicas, sin usar jerga actuarial compleja. 
            El tono debe ser profesional, agradecido por su fidelidad y enfocado en la protección continua que le brinda la póliza.
            No incluyas saludos genéricos como [Nombre del Cliente], usa "Estimado Cliente".
            """
            
            respuesta = modelo.generate_content(prompt)
            texto_carta = respuesta.text
            
            st.markdown("### Vista Previa de la Carta:")
            st.write(texto_carta)
            
            # 2. Generación del archivo Word en memoria
            doc = Document()
            doc.add_heading(f'Propuesta de Renovación - Póliza {poliza_seleccionada}', 0)
            doc.add_paragraph(texto_carta)
            
            # Guardamos el documento en un buffer de memoria en vez del disco duro
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            # 3. Botón nativo de Streamlit para descargar el Word
            st.download_button(
                label="📥 Descargar Carta en Word (.docx)",
                data=buffer,
                file_name=f"Renovacion_Poliza_{poliza_seleccionada}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary"
            )