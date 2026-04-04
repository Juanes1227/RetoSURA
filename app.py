import streamlit as st
import pandas as pd
import numpy as np
import openpyxl

# 1. Configuración básica
st.set_page_config(page_title="Cotizador de Renovaciones", page_icon="🛡️", layout="wide")

st.title("🛡️ Herramienta de Tarifación para Renovaciones")

# Inicializar la "memoria" de Streamlit
if 'datos_procesados' not in st.session_state:
    st.session_state['datos_procesados'] = None

# 2. Función de procesamiento de datos
@st.cache_data(show_spinner=False)
def procesar_datos(file_polizas, file_curva, file_siniestros):
    siniestros = pd.read_excel(file_siniestros)
    curva_riesgo = pd.read_excel(file_curva)
    polizas = pd.read_csv(file_polizas, sep='|', decimal=",")
    
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

# 3. Lógica de la Interfaz en la Barra Lateral
st.sidebar.header("📂 1. Gestión de Datos")

# Si NO hay datos en memoria, mostramos los cargadores de archivos
if st.session_state['datos_procesados'] is None:
    st.info("👈 Sube los archivos en la barra lateral para comenzar el análisis.")
    st.sidebar.markdown("Sube los archivos más recientes:")
    
    file_polizas = st.sidebar.file_uploader("1. Pólizas Vigentes (.txt)", type=['txt', 'csv'])
    file_curva = st.sidebar.file_uploader("2. Curva de Riesgo (.xlsx)", type=['xlsx'])
    file_siniestros = st.sidebar.file_uploader("3. Siniestros Históricos (.xlsx)", type=['xlsx'])

    # Botón para procesar solo cuando los 3 archivos estén cargados
    if file_polizas and file_curva and file_siniestros:
        if st.sidebar.button("Procesar y Guardar Datos"):
            with st.spinner("Procesando modelos... esto puede tomar unos segundos."):
                try:
                    df = procesar_datos(file_polizas, file_curva, file_siniestros)
                    st.session_state['datos_procesados'] = df # Guardamos en memoria
                    st.rerun() # Recargamos la página para ocultar los botones de carga
                except Exception as e:
                    st.sidebar.error(f"Error al procesar: {e}")

# Si YA hay datos en memoria, mostramos el buscador
else:
    st.sidebar.success("✅ Base de datos cargada en memoria.")
    
    # Botón para reiniciar si quieren subir archivos nuevos el próximo mes
    if st.sidebar.button("🔄 Cargar nuevos archivos"):
        st.session_state['datos_procesados'] = None
        st.rerun()

    st.sidebar.divider()
    st.sidebar.header("🔍 2. Consultar Póliza")
    
    # Llamamos a los datos desde la memoria
    df_resultados = st.session_state['datos_procesados']
    
    # El buscador ahora funcionará sin interrumpir nada
    lista_polizas = df_resultados['Poliza_Id'].astype(str).unique()
    poliza_seleccionada = st.sidebar.selectbox("Ingrese o seleccione el ID de la póliza:", lista_polizas)

    # 4. Flujo Principal: Resultados Visuales
    datos_poliza = df_resultados[df_resultados['Poliza_Id'].astype(str) == poliza_seleccionada].iloc[0]

    st.header(f"Resultados para la Póliza: `{poliza_seleccionada}`")

    # Tarjetas de Tasas y Credibilidad
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Factor de Credibilidad (Z)", value=f"{datos_poliza['Z'] * 100:.2f}%")
    with col2:
        st.metric(label="Tasa Pura de Riesgo (TPR)", value=f"{datos_poliza['Tasa Unica pura de riesgo']:.4f}")
    with col3:
        diferencia_tasa = datos_poliza['tasa_cred'] - datos_poliza['Tasa Unica pura de riesgo']
        st.metric(label="Tasa Credibilizada", value=f"{datos_poliza['tasa_cred']:.4f}", 
                  delta=f"{diferencia_tasa:.4f} vs Pura", delta_color="inverse")
    with col4:
        st.metric(label="Tasa Comercial Unica", value=f"{datos_poliza['Tasa Unica comercial']:.4f}")

    st.divider()

    # Tarjetas de Primas
    st.subheader("Comparativo Financiero")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.info(f"**Valor Asegurado (Solo Vida):**\n\n${datos_poliza['VA_Solo_Vida']:,.2f}")
    with col_b:
        st.warning(f"**Prima Actual (Por Cobertura):**\n\n${datos_poliza['Prima por Cobertura']:,.2f}")
    with col_c:
        st.success(f"**PRIMA RECOMENDADA NUEVA:**\n\n${datos_poliza['prima_recomendada']:,.2f}")

    # Detalle en tabla
    with st.expander("Ver tabla completa de la póliza (Detalles crudos)"):
        st.dataframe(pd.DataFrame(datos_poliza).T, use_container_width=True)