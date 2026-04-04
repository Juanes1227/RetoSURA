import streamlit as st
import pandas as pd
import numpy as np
import openpyxl

# 1. Configuración básica
st.set_page_config(page_title="Cotizador de Renovaciones", page_icon="🛡️", layout="wide")
st.title("🛡️ Herramienta de Tarifación para Renovaciones")

# 2. Inicializar la "Memoria" de las bases de datos individuales
# Así podemos actualizar una sin borrar las otras.
for key in ['df_polizas', 'df_curva', 'df_siniestros', 'datos_procesados']:
    if key not in st.session_state:
        st.session_state[key] = None

# 3. Función de procesamiento (ahora recibe DataFrames, no archivos)
@st.cache_data(show_spinner=False)
def procesar_datos(polizas_raw, curva_raw, siniestros_raw):
    # Hacemos copias para no alterar los datos crudos en memoria
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

# Indicadores de estado visuales
estado_p = "🟢" if st.session_state['df_polizas'] is not None else "🔴"
estado_c = "🟢" if st.session_state['df_curva'] is not None else "🔴"
estado_s = "🟢" if st.session_state['df_siniestros'] is not None else "🔴"
st.sidebar.markdown(f"{estado_p} Pólizas | {estado_c} Curva | {estado_s} Siniestros")
st.sidebar.divider()

# A. Actualizar Pólizas (Permite Update/Insert)
with st.sidebar.expander("📄 Cargar / Actualizar Pólizas"):
    file_polizas = st.file_uploader("Archivo de Pólizas (.txt, .csv)", type=['txt', 'csv'], key="up_polizas")
    modo_carga = st.radio("Acción a realizar:", ["Reemplazar toda la base", "Actualizar / Agregar específicas"])
    
    if st.button("Aplicar Pólizas") and file_polizas:
        df_nuevo = pd.read_csv(file_polizas, sep='|', decimal=",")
        
        if modo_carga == "Reemplazar toda la base" or st.session_state['df_polizas'] is None:
            st.session_state['df_polizas'] = df_nuevo
            st.success("Base de pólizas reemplazada con éxito.")
        else:
            # Lógica de Upsert (Actualizar y Agregar)
            ids_nuevos = df_nuevo['Poliza_Id'].unique()
            df_actual = st.session_state['df_polizas']
            # Quitamos los registros viejos de las pólizas que estamos actualizando
            df_actual = df_actual[~df_actual['Poliza_Id'].isin(ids_nuevos)]
            # Unimos la base vieja (limpia) con los datos nuevos
            st.session_state['df_polizas'] = pd.concat([df_actual, df_nuevo], ignore_index=True)
            st.success(f"Se actualizaron/agregaron {len(ids_nuevos)} pólizas exitosamente.")

# B. Actualizar Curva
with st.sidebar.expander("📈 Cargar / Actualizar Curva de Riesgo"):
    file_curva = st.file_uploader("Archivo Curva (.xlsx)", type=['xlsx'], key="up_curva")
    if st.button("Aplicar Curva") and file_curva:
        st.session_state['df_curva'] = pd.read_excel(file_curva)
        st.success("Curva de riesgo actualizada.")

# C. Actualizar Siniestros
with st.sidebar.expander("💥 Cargar / Actualizar Siniestros"):
    file_siniestros = st.file_uploader("Archivo Siniestros (.xlsx)", type=['xlsx'], key="up_siniestros")
    if st.button("Aplicar Siniestros") and file_siniestros:
        st.session_state['df_siniestros'] = pd.read_excel(file_siniestros)
        st.success("Siniestros históricos actualizados.")

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
                st.sidebar.success("✅ Cálculos actualizados.")
            except Exception as e:
                st.sidebar.error(f"Error al calcular: {e}")
else:
    st.sidebar.info("Carga las 3 bases de datos (🟢) para habilitar el cálculo.")


# 5. PANTALLA PRINCIPAL: Buscador y Resultados
if st.session_state['datos_procesados'] is not None:
    df_resultados = st.session_state['datos_procesados']
    
    st.subheader("🔍 2. Consultar Póliza")
    
    # Sistema de búsqueda dual (Teclado o Lista)
    col_busqueda1, col_busqueda2 = st.columns(2)
    with col_busqueda1:
        busqueda_texto = st.text_input("Buscar por ID de Póliza (Escriba y presione Enter):", placeholder="Ej: 109553448")
    with col_busqueda2:
        lista_polizas = df_resultados['Poliza_Id'].astype(str).unique()
        busqueda_lista = st.selectbox("O seleccione de la lista:", [""] + list(lista_polizas))

    # Determinar qué póliza usar (prioridad al texto si se escribió algo)
    poliza_seleccionada = busqueda_texto if busqueda_texto != "" else busqueda_lista

    if poliza_seleccionada:
        # Validar si la póliza existe
        if poliza_seleccionada in lista_polizas:
            datos_poliza = df_resultados[df_resultados['Poliza_Id'].astype(str) == poliza_seleccionada].iloc[0]

            st.header(f"Resultados para la Póliza: `{poliza_seleccionada}`")

            # Tarjetas de Tasas y Credibilidad
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

            # Tarjetas de Primas
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