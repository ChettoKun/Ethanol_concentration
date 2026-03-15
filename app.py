import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
from PIL import Image
import os

# =================================================================
# 1. CONFIGURACIÓN DE PÁGINA
# =================================================================
st.set_page_config(page_title="BioSTEAM Engineering Suite", layout="wide")

# Configuración de Gemini con manejo de errores
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.warning("⚠️ API Key de Gemini no detectada. La sección de IA estará desactivada.")

# =================================================================
# 2. MOTOR DE SIMULACIÓN
# =================================================================
def ejecutar_simulacion(f_agua, f_etanol, t_entrada):
    # Limpieza total del flujo de trabajo para evitar IDs duplicados
    bst.main_flowsheet.clear()
    
    # Configuración de componentes
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    # Corrientes
    mosto = bst.Stream("1_MOSTO", Water=f_agua, Ethanol=f_etanol, 
                       units="kg/hr", T=t_entrada + 273.15)
    
    vinazas_retorno = bst.Stream("Vinazas_Retorno", Water=200, Ethanol=0, 
                                 units="kg/hr", T=95 + 273.15, P=300000)

    # Equipos
    P100 = bst.Pump("P100", ins=mosto, P=4*101325)
    
    W210 = bst.HXprocess("W210", ins=(P100-0, vinazas_retorno),
                       outs=("3_Mosto_Pre", "Drenaje"),
                       phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15

    W220 = bst.HXutility("W220", ins=W210-0, outs="Mezcla", T=92+273.15)
    V100 = bst.IsenthalpicValve("V100", ins=W220-0, outs="Mezcla_Bifasica", P=101325)
    V1 = bst.Flash("V1", ins=V100-0, outs=("Vapor_caliente", "Vinazas"), P=101325, Q=0)
    W310 = bst.HXutility("W310", ins=V1-0, outs="Producto_Final", T=25 + 273.15)
    P200 = bst.Pump("P200", ins=V1-1, outs=vinazas_retorno, P=3*101325)

    # Sistema
    eth_sys = bst.System("planta_etanol", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, None
    except Exception as e:
        return None, str(e)

# =================================================================
# 3. INTERFAZ DE USUARIO
# =================================================================
st.title("🧪 Simulador de Procesos BioSTEAM + AI")
st.markdown("---")

# Barra lateral
st.sidebar.header("⚙️ Parámetros de Operación")
f_agua = st.sidebar.slider("Agua en alimentación (kg/h)", 500, 2000, 900)
f_etanol = st.sidebar.slider("Etanol en alimentación (kg/h)", 10, 500, 100)
t_entrada = st.sidebar.number_input("Temperatura de Entrada (°C)", value=25)

if st.sidebar.button("🚀 Ejecutar Simulación"):
    sys, error = ejecutar_simulacion(f_agua, f_etanol, t_entrada)
    
    if error:
        st.error(f"Error en la simulación: {error}")
    else:
        # Pestañas para organizar info
        tab1, tab2, tab3 = st.tabs(["📊 Resultados", "🖼️ Diagrama de Proceso", "🤖 Tutor de IA"])
        
        # Procesamiento de datos
        datos_mat = []
        for s in sys.streams:
            if s.F_mass > 0:
                datos_mat.append({
                    "Stream": s.ID,
                    "Temp (°C)": f"{s.T - 273.15:.2f}",
                    "Flujo (kg/h)": f"{s.F_mass:.2f}",
                    "EtOH %": f"{(s.imass['Ethanol']/s.F_mass)*100:.1f}%"
                })
        df_m = pd.DataFrame(datos_mat)

        with tab1:
            st.subheader("Balance de Materia y Energía")
            st.table(df_m)
            
        with tab2:
            st.subheader("Diagrama de Flujo del Proceso (PFD)")
            # Guardamos y cargamos manualmente para evitar errores de renderizado de Streamlit
            try:
                sys.diagram(file="pfd_output", format="png")
                image = Image.open("pfd_output.png")
                st.image(image, caption="PFD Generado por BioSTEAM")
            except Exception as e:
                st.warning(f"No se pudo generar el diagrama: {e}")

        with tab3:
            if "GEMINI_API_KEY" in st.secrets:
                with st.spinner("El Ingeniero IA está analizando los datos..."):
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    prompt = f"""
                    Eres un Ingeniero de Procesos experto. Analiza estos resultados de una simulación de separación flash:
                    {df_m.to_string()}
                    
                    Dime:
                    1. ¿Es buena la recuperación de etanol en el 'Vapor_caliente'?
                    2. ¿Ves algún problema térmico o de flujo?
                    3. Sugerencia técnica para optimizar la pureza.
                    """
                    response = model.generate_content(prompt)
                    st.write(response.text)
            else:
                st.info("Configura tu GEMINI_API_KEY para recibir consejos técnicos.")
