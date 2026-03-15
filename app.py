import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
import os

# =================================================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS
# =================================================================
st.set_page_config(page_title="BioSTEAM Web Simulator", layout="wide")

# Configuración de la API de Gemini
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except:
    st.error("Falta la GEMINI_API_KEY en los Secrets de Streamlit.")

# =================================================================
# 2. LÓGICA DE SIMULACIÓN (ENCAPSULADA)
# =================================================================
def ejecutar_simulacion(f_agua, f_etanol, t_entrada):
    # CRÍTICO: Limpiar el flowsheet para evitar "Duplicate ID" al mover sliders
    bst.main_flowsheet.clear()
    
    # Configuración Termodinámica
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    # Definición de Corrientes
    mosto = bst.Stream("1-MOSTO",
                     Water=f_agua, Ethanol=f_etanol, units="kg/hr",
                     T=t_entrada + 273.15, P=101325)

    vinazas_retorno = bst.Stream("Vinazas-Retorno",
                               Water=200, Ethanol=0, units="kg/hr",
                               T=95 + 273.15, P=300000)

    # Selección de Equipos
    P100 = bst.Pump("P100", ins=mosto, P=4*101325)
    
    W210 = bst.HXprocess("W210",
                       ins=(P100-0, vinazas_retorno),
                       outs=("3-Mosto-Pre", "Drenaje"),
                       phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15

    W220 = bst.HXutility("W220", ins=W210-0, outs="Mezcla", T=92+273.15)
    
    V100 = bst.IsenthalpicValve("V100", ins=W220-0, outs="Mezcla-Bifasica", P=101325)
    
    V1 = bst.Flash("V1", ins=V100-0, outs=("Vapor_caliente", "Vinazas"), P=101325, Q=0)
    
    W310 = bst.HXutility("W310", ins=V1-0, outs="Producto_Final", T=25 + 273.15)
    
    P200 = bst.Pump("P200", ins=V1-1, outs=vinazas_retorno, P=3*101325)

    # Definición del Sistema
    eth_sys = bst.System("planta_etanol", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, None
    except Exception as e:
        return None, str(e)

# =================================================================
# 3. FUNCIONES DE REPORTE Y DIAGRAMA
# =================================================================
def generar_tablas(sistema):
    # Tabla de Materia
    datos_mat = []
    for s in sistema.streams:
        if s.F_mass > 0:
            datos_mat.append({
                "ID Corriente": s.ID,
                "Temp (°C)": round(s.T - 273.15, 2),
                "Flujo (kg/h)": round(s.F_mass, 2),
                "% Etanol": f"{s.imass['Ethanol']/s.F_mass:.1%}" if s.F_mass > 0 else "0%"
            })
    
    # Tabla de Energía (Manejo de errores .duty)
    datos_en = []
    for u in sistema.units:
        calor_kw = 0.0
        # Caso HXprocess o equipos sin duty directo
        if hasattr(u, 'heat_utilities') and u.heat_utilities:
            calor_kw = sum([hu.duty for hu in u.heat_utilities]) / 3600
        elif isinstance(u, bst.HXprocess):
            calor_kw = (u.outs[0].H - u.ins[0].H) / 3600

        if abs(calor_kw) > 0.01:
            datos_en.append({"Equipo": u.ID, "Energía (kW)": round(calor_kw, 2)})

    return pd.DataFrame(datos_mat), pd.DataFrame(datos_en)

# =================================================================
# 4. INTERFAZ DE USUARIO (STREAMLIT)
# =================================================================
st.sidebar.header("Parámetros de Entrada")
f_agua = st.sidebar.number_input("Flujo de Agua (kg/h)", value=900)
f_etanol = st.sidebar.number_input("Flujo de Etanol (kg/h)", value=100)
t_entrada = st.sidebar.slider("Temperatura de Entrada (°C)", 10, 50, 25)

if st.sidebar.button("Ejecutar Simulación"):
    sys, error = ejecutar_simulacion(f_agua, f_etanol, t_entrada)
    
    if error:
        st.error(f"Error en la simulación: {error}")
    else:
        df_m, df_e = generar_tablas(sys)
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Balance de Materia")
            st.dataframe(df_m)
        with col2:
            st.subheader("Consumo Energético")
            st.dataframe(df_e)
            
        # Generar Diagrama
        st.subheader("Diagrama de Flujo (PFD)")
        sys.diagram(file="pfd", format="png")
        st.image("pfd.png")

        # Integración con Gemini
        st.divider()
        st.subheader("💡 Análisis del Tutor de IA")
        with st.spinner("Consultando a Gemini..."):
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Como ingeniero químico, analiza estos resultados de simulación de una columna flash y dime si la separación es eficiente: {df_m.to_string()}"
            response = model.generate_content(prompt)
            st.write(response.text)
