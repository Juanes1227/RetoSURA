import streamlit as st
import pandas as pd
import numpy as np
import openpyxl


# 1. Configuración básica de la página
st.set_page_config(
    page_title="Cotizador de Renovaciones", 
    page_icon="🛡️", 
    layout="wide"
)

st.title("🛡️ Herramienta de Tarifación para Renovaciones")
st.markdown("""
Sube los archivos fuente actualizados en la barra lateral para calcular las condiciones 
de tarifación. Luego, consulta por número de póliza las sugerencias para la nueva vigencia.
""")

# 2. Función de procesamiento de datos (Tu código integrado)
@st.cache_data(show_spinner="Procesando modelos de tarifación y credibilidad...")
def procesar_datos(file_polizas, file_curva, file_siniestros):
    # Lectura de los archivos subidos
    siniestros = pd.read_excel(file_siniestros)
    curva_riesgo = pd.read_excel(file_curva)
    polizas = pd.read_csv(file_polizas, sep='|', decimal=",")
    
    # NOTA: En tu código original se llamaba a "curva_siniestros" que parecía ser la unión 
    # de siniestros y pólizas para obtener "VA_Ajuste_Prueba". Hacemos el merge aquí:
    curva_siniestros = pd.merge(siniestros, polizas, on='Poliza_Id', how='left')

    # Cálculo TPR
    TPR = curva_siniestros["Valor del Siniestro"].mean() / (curva_siniestros["VA_Ajuste_Prueba"].mean() * 100)

    # Cruce de riesgo y pólizas
    polizas_riesgo = pd.merge(polizas, curva_riesgo, left_on=['Amparo_Id', 'Edad_Cliente'], right_on=['Amparo_ID', 'Edad'], how='inner')
    polizas_riesgo["PPRC"] = polizas_riesgo["VA_Ajuste_Prueba"] * polizas_riesgo["Tasa"]
    polizas_riesgo["TCPC"] = polizas_riesgo["Tasa"] / (1 - 0.4)
    polizas_riesgo['VA_Solo_Vida'] = np.where(polizas_riesgo['Amparo_Desc'].str.startswith('VIDA', na=False), polizas_riesgo['VA_Ajuste_Prueba'], 0)

    tasa_unica_poliza = polizas_riesgo.groupby(['Poliza_Id'])[['PPRC', "VA_Solo_Vida"]].sum().reset_index()
    tasa_unica_poliza = tasa_unica_poliza.rename(columns={'PPRC': 'Prima por Cobertura'})
    tasa_unica_poliza["Tasa Unica pura de riesgo"] = tasa_unica_poliza["Prima por Cobertura"] / tasa_unica_poliza["VA_Solo_Vida"]
    tasa_unica_poliza["Tasa Unica comercial"] = tasa_unica_poliza["Tasa Unica pura de riesgo"] / (1 - 0.4)

    # Cálculos Siniestros
    siniestros["n"] = siniestros.groupby(['Poliza_Id'])["Poliza_Id"].transform('count')
    siniestros['Valor_Calculo'] = np.where(siniestros['Valor del Siniestro'] > 2350, 2350, siniestros['Valor del Siniestro'])
    siniestros["varianza_por_cliente"] = siniestros.groupby('Poliza_Id')['Valor_Calculo'].transform('var', ddof=1).fillna(0)
    siniestros["media_por_cliente"] = siniestros.groupby('Poliza_Id')['Valor_Calculo'].transform('mean').fillna(0)

    siniestros_gb = siniestros.groupby(['Poliza_Id']).agg({
        'Valor del Siniestro': 'mean',
        'n': 'mean',
        'varianza_por_cliente': 'mean',
        'media_por_cliente': 'mean'
    }).reset_index()

    curva_siniestros["Valor_Calculo"] = curva_siniestros["Valor del Siniestro"].clip(upper=181418.13)
    siniestros_gb_ = curva_siniestros.groupby('Poliza_Id')['Valor_Calculo'].agg(['mean', 'var']).fillna(0)

    # Parámetros de Bühlmann
    EPV = siniestros_gb_['var'].mean()
    VHM = siniestros_gb_['mean'].var(ddof=1)
    K_nuevo = EPV / VHM if VHM != 0 else 0

    siniestros_gb["K"] = K_nuevo
    siniestros_gb["Z"] = (siniestros_gb["n"] / (siniestros_gb["n"] + siniestros_gb["K"]))

    # Consolidación Final
    tasa_unica_poliza = pd.merge(tasa_unica_poliza, siniestros_gb[['Poliza_Id', 'Z']], on='Poliza_Id', how='left')
    tasa_unica_poliza["Z"] = tasa_unica_poliza["Z"].fillna(0)
    tasa_unica_poliza["tasa_cred"] = (tasa_unica_poliza["Z"] * tasa_unica_poliza["Tasa Unica pura de riesgo"]) + ((1 - tasa_unica_poliza["Z"]) * TPR)
    tasa_unica_poliza["prima_recomendada"] = tasa_unica_poliza["tasa_cred"] * tasa_unica_poliza["VA_Solo_Vida"]

    return tasa_unica_poliza

# 3. Barra Lateral: Carga de Archivos
st.sidebar.header("📂 1. Actualización de Datos")
st.sidebar.markdown("Sube los archivos más recientes:")

file_polizas = st.sidebar.file_uploader("1. Pólizas Vigentes (.txt)", type=['txt', 'csv'])
file_curva = st.sidebar.file_uploader("2. Curva de Riesgo (.xlsx)", type=['xlsx'])
file_siniestros = st.sidebar.file_uploader("3. Siniestros Históricos (.xlsx)", type=['xlsx'])

# 4. Flujo Principal: Procesamiento y Visualización
if file_polizas and file_curva and file_siniestros:
    try:
        # Procesar los datos con la función (está cacheada para no recalcular si no cambian los archivos)
        df_resultados = procesar_datos(file_polizas, file_curva, file_siniestros)
        st.sidebar.success("✅ Datos procesados correctamente")

        # Buscador de Póliza
        st.sidebar.divider()
        st.sidebar.header("🔍 2. Consultar Póliza")
        lista_polizas = df_resultados['Poliza_Id'].astype(str).unique()
        poliza_seleccionada = st.sidebar.selectbox("Ingrese o seleccione el ID:", lista_polizas)

        # Filtrar información
        datos_poliza = df_resultados[df_resultados['Poliza_Id'].astype(str) == poliza_seleccionada].iloc[0]

        # Interfaz de Resultados Visuales
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

        # Opcional: Mostrar resumen de los datos calculados
        with st.expander("Ver tabla completa de la póliza (Detalles crudos)"):
            st.dataframe(pd.DataFrame(datos_poliza).T, use_container_width=True)

    except Exception as e:
        st.error(f"Ocurrió un error al procesar los archivos. Verifica los formatos y columnas. Detalle: {e}")

else:
    # Mensaje mientras no se suben los archivos
    st.info("👈 Por favor, carga los 3 archivos en el panel izquierdo para comenzar el análisis.")