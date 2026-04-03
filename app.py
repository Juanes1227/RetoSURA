import streamlit as st
import pandas as pd


def main():
    st.set_page_config(page_title="Cargador de Archivos", page_icon="📂", layout="wide")
    
    st.title("Mi Aplicación con Layout")

    # 1. Definimos las columnas (Proporción 1:3)
    col_a, col_b = st.columns([3, 1])

    # --- COLUMNA A ---
    with col_a:
        st.header("Columna A")
        st.write("Este es el panel lateral o de instrucciones.")
        st.info("Puedes poner aquí filtros o parámetros.")

    # --- COLUMNA B (Aquí metemos tu lógica) ---
    with col_b:
        st.header("📂 Cargar datos")
        st.write("Sube un archivo para analizar su contenido.")

        # El widget de carga ahora vive dentro de col_b
        uploaded_file = st.file_uploader(
            "Elige un archivo (CSV o Excel)", 
            type=["csv", "xlsx"]
        )

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)

                st.success("¡Archivo cargado con éxito!")
                
                st.subheader("Vista Previa de los Datos")
                st.dataframe(df.head()) 

                st.subheader("Estadísticas Rápidas")
                st.write(df.describe())

            except Exception as e:
                st.error(f"Error al procesar el archivo: {e}")
        else:
            st.info("Esperando a que subas un archivo en este espacio...")

if __name__ == "__main__":
    main()