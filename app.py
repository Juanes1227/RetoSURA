import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Mi App Pro",
    page_icon="🚀",
    layout="wide", # Usa todo el ancho de la pantalla en lugar de un bloque central
    initial_sidebar_state="expanded"
)

col1, col2 = st.columns([2, 1])

with col1:
    st.header("Columna A")
    st.info("Aquí va información.")

with col2:
    with st.container(border=True): # Crea un recuadro visual
        st.header("Columna B")
        st.write("Este contenido está dentro de un borde.")

def main():
    st.set_page_config(page_title="Cargador de Archivos", page_icon="📂")
    
    st.title("📂 Cargador de Datos")
    st.write("Sube un archivo para analizar su contenido.")

    # El widget mágico de Streamlit
    uploaded_file = st.file_uploader(
        "Elige un archivo (CSV o Excel)", 
        type=["csv", "xlsx"]
    )

    if uploaded_file is not None:
        try:
            # Identificar la extensión para leerlo correctamente
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            # Mostrar información del archivo
            st.success("¡Archivo cargado con éxito!")
            
            st.subheader("Vista Previa de los Datos")
            st.dataframe(df.head()) # Muestra las primeras 5 filas

            st.subheader("Estadísticas Rápidas")
            st.write(df.describe())

        except Exception as e:
            st.error(f"Error al procesar el archivo: {e}")
    else:
        st.info("Esperando a que subas un archivo...")

if __name__ == "__main__":
    main()