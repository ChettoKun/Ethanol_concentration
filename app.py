import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
import os

# =================================================================
# 1. CONFIGURACIÓN DE PÁGINA
# =================================================================
st.set_page_config(page_title="BioSTEAM Expert Simulator", layout="wide")

# Configuración de la API de Gemini con manejo de errores
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.warning("⚠️ GEMINI_API_KEY no encontrada en Secrets. El tutor de IA estará desactivado.")

# =================================================================
# 2. LÓGICA DE SIMULACIÓN (ENCAPSULADA)
# =================================================================
def ejecutar_simulacion(f_agua, f_etanol, t_entrada):
    # CRÍTICO: Limpiar el flowsheet para evitar errores de ID duplicado
    bst.main_flowsheet.clear()
    
    # Configuración Termodinámica
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    # Definición de Corrientes
    mosto = bst.Stream("mosto_entrada",
                     Water=f_agua, Ethanol=f_etanol, units="kg/hr",
                     T=t_entrada + 273.15, P=101325)

    vinazas_retorno = bst.Stream("vinazas_retorno",
                               Water=200, Ethanol=0, units="kg/hr",
                               T=95 + 273.15, P=300000)

    # Selección de Equipos
    P100 = bst.Pump("P100", ins=mosto, P=4*101325)
    
    W210 = bst.HXprocess("W210",
                       ins=(P100-0, vinazas_retorno),
                       outs=("mosto_precalentado", "drenaje_vinazas"),
                       phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15

    W220 = bst.HXutility("W220", ins=W210-0, outs="mezcla_caliente", T=92+273.15)
    
    V100 = bst.IsenthalpicValve("V100", ins=W220-0, outs="mezcla_bifasica", P=101325)
    
    V1 = bst.Flash("V1", ins=V100-0, outs=("vapor_etanol", "vinazas_fondo"), P=101325, Q=0)
    
    W310 = bst.HXutility("W310", ins=V1-0, outs="producto_final", T=25 + 273.15)
    
    P200 = bst.Pump("P200", ins=V1-1, outs=vinazas_retorno, P=3*101325)

    # Definición del Sistema
    eth_sys = bst.System("sistema_etanol", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, None
    except Exception as e:
        return None, str(e)

# =================================================================
# 3. FUNCIONES DE REPORTE
# =================================================================
def generar_tablas(sistema):
    datos_mat = []
    for s in sistema.streams:
        if s.F_mass > 0:
            datos_mat.append({
                "ID Corriente": s.ID,
                "Temp (°C)": round(s.T - 273.15, 2),
                "Flujo Total (kg/h)": round(s.F_mass, 2),
                "Etano (kg/h)": round(s.imass['Ethanol'], 2),
                "% Etanol": f"{(s.imass['Ethanol']/s.F_mass)*100:.2f}%"
            })
    
    datos_en = []
    for u in sistema.units:
        calor_kw = 0.0
        if hasattr(u, 'heat_utilities') and u.heat_utilities:
            calor_kw = sum([hu.duty for hu in u.heat_utilities]) / 3600
        elif isinstance(u, bst.HXprocess):
            calor_kw = (u.outs[0].H - u.ins[0].H) / 3600

        if abs(calor_kw) > 0.001:
            datos_en.append({"Equipo": u.ID, "Carga Térmica (kW)": round(calor_kw, 2)})

    return pd.DataFrame(datos_mat), pd.DataFrame(datos_en)

# =================================================================
# 4. INTERFAZ DE USUARIO (STREAMLIT)
# =================================================================
st.title("🧪 Simulador de Separación de Etanol")
st.markdown("Desarrollado con **BioSTEAM** y analizado por **Gemini IA**.")

with st.sidebar:
    st.header("⚙️ Parámetros de Proceso")
    f_agua = st.slider("Flujo de Agua (kg/h)", 500, 2000, 900)
    f_etanol = st.slider("Flujo de Etanol (kg/h)", 10, 500, 100)
    t_entrada = st.number_input("Temperatura Entrada (°C)", value=25)
    btn_simular = st.button("🚀 Ejecutar Simulación", use_container_width=True)

if btn_simular:
    sys, error = ejecutar_simulacion(f_agua, f_etanol, t_entrada)
    
    if error:
        st.error(f"Error en la convergencia: {error}")
    else:
        df_m, df_e = generar_tablas(sys)
        
        tab1, tab2, tab3 = st.tabs(["📊 Balances", "📐 Diagrama PFD", "🤖 Tutor IA"])
        
        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Balance de Materia**")
                st.dataframe(df_m, use_container_width=True)
            with col2:
                st.write("**Balance de Energía**")
                st.dataframe(df_e, use_container_width=True)
            
        with tab2:
            st.write("**Diagrama de Flujo del Proceso**")
            try:
                sys.diagram(file="pfd", format="png")
                st.image("pfd.png")
            except:
                st.info("El diagrama se está generando, intenta recargar en un momento.")

        with tab3:
            if "GEMINI_API_KEY" in st.secrets:
                with st.spinner("El ingeniero IA está analizando los datos..."):
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    analisis_prompt = f"""
                    Analiza como ingeniero químico estos resultados de una simulación BioSTEAM:
                    TABLA DE MATERIA:
                    {df_m.to_string()}
                    
                    TABLA DE ENERGÍA:
                    {df_e.to_string()}
                    
                    ¿Es eficiente la separación en el tanque Flash? ¿Qué recomendarías para mejorar la pureza del etanol en el vapor?
                    """
                    response = model.generate_content(analisis_prompt)
                    st.markdown(response.text)
            else:
                st.error("Configura la API Key para usar esta función.")
