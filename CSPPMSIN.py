import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import datetime, timedelta
import calendar

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y CSS MINIMALISTA
# ==========================================
st.set_page_config(page_title="Dashboard EVM", layout="wide", page_icon="🏭")

st.markdown("""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 1rem; padding-left: 1.5rem; padding-right: 1.5rem; max-width: 100%; }
        .metric-card {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(150, 150, 150, 0.15);
            border-radius: 6px;
            padding: 12px 16px;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
            margin-bottom: 10px;
        }
        .metric-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; }
        .metric-title { font-size: 11px; text-transform: uppercase; font-weight: 600; color: var(--text-color); opacity: 0.7; }
        .metric-icon { font-size: 15px; opacity: 0.9; }
        .icon-blue { color: #1f77b4; }
        .icon-green { color: #2ca02c; }
        .icon-orange { color: #ff7f0e; }
        .icon-red { color: #d62728; }
        .icon-gray { color: #7f7f7f; }
        .metric-value { font-size: 22px; font-weight: 500; color: var(--text-color); line-height: 1;}
        h1, h2, h3, h4, h5 { padding-bottom: 0px !important; margin-bottom: 8px !important; margin-top: 0px !important;}
        hr { margin: 15px 0 !important; border-color: rgba(130, 130, 130, 0.15) !important; }
        .stTextArea textarea { min-height: 120px; font-size: 13px;}
    </style>
""", unsafe_allow_html=True)

def card_html(title, value, icon, color_class):
    return f"""
    <div class="metric-card">
        <div class="metric-header">
            <span class="metric-title">{title}</span>
            <i class="{icon} icon-{color_class} metric-icon"></i>
        </div>
        <div class="metric-value">{value}</div>
    </div>
    """

# ==========================================
# 2. FUNCIONES DE CARGA Y PROCESAMIENTO
# ==========================================

@st.cache_data
def cargar_datos():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta_tareas = os.path.join(base_dir, "Consolidado_Tareas_General.csv")
    fecha_modificacion = "Desconocida"
    if os.path.exists(ruta_tareas):
        timestamp = os.path.getmtime(ruta_tareas)
        fecha_modificacion = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y - %I:%M %p')
        df_tareas = pd.read_csv(ruta_tareas, sep=';')
        for col in ['Inicio_Planificado', 'Fin_Planificado', 'Inicio_Real', 'Fin_Real']:
            df_tareas[col] = pd.to_datetime(df_tareas[col], errors='coerce', dayfirst=True)
        return df_tareas, fecha_modificacion
    return pd.DataFrame(), fecha_modificacion

@st.cache_data
def procesar_serie_tiempo_evm(df_crudo, fecha_corte_corte):
    if df_crudo.empty: return pd.DataFrame()
    peso_total = df_crudo['Duracion_Dias'].sum()
    if peso_total == 0: peso_total = 1 
    
    fechas_plan, fechas_real = [], []
    corte_ts = pd.Timestamp(fecha_corte_corte).normalize()
    
    for _, tarea in df_crudo.dropna(subset=['Inicio_Planificado', 'Fin_Planificado']).iterrows():
        rango = pd.date_range(start=tarea['Inicio_Planificado'], end=tarea['Fin_Planificado'])
        if len(rango) > 0:
            fechas_plan.extend([{'Fecha': f, 'PV': tarea['Duracion_Dias'] / len(rango)} for f in rango])
                
    for _, tarea in df_crudo.dropna(subset=['Inicio_Real']).iterrows():
        if tarea['Inicio_Real'] > corte_ts: continue
        pct = pd.to_numeric(tarea['Avance_Fisico_Pct'], errors='coerce')
        if pd.isna(pct): pct = 0
        ev_tarea = tarea['Duracion_Dias'] * (pct / 100)
        
        if ev_tarea > 0:
            inicio = tarea['Inicio_Real']
            fin = tarea['Fin_Real'] if pd.notna(tarea['Fin_Real']) else corte_ts
            if fin < inicio: fin = inicio
            if fin > corte_ts: fin = corte_ts
            rango_real = pd.date_range(start=inicio, end=fin)
            if len(rango_real) > 0:
                fechas_real.extend([{'Fecha': f, 'EV': ev_tarea / len(rango_real)} for f in rango_real])
                    
    df_plan = pd.DataFrame(fechas_plan).groupby('Fecha')['PV'].sum().reset_index() if fechas_plan else pd.DataFrame(columns=['Fecha', 'PV'])
    df_real = pd.DataFrame(fechas_real).groupby('Fecha')['EV'].sum().reset_index() if fechas_real else pd.DataFrame(columns=['Fecha', 'EV'])
    
    df = pd.merge(df_plan, df_real, on='Fecha', how='outer').sort_values('Fecha').fillna(0)
    
    if not df.empty:
        df['Porcentaje_Planificado'] = df['PV'].cumsum() / peso_total
        df['Porcentaje_Fisico'] = df['EV'].cumsum() / peso_total
        df['SV_Porcentaje'] = (df['Porcentaje_Fisico'] - df['Porcentaje_Planificado']) * 100
        df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date 
    return df

def calcular_kpis_a_la_fecha(df_curvas, fecha_corte):
    df_historico = df_curvas[df_curvas['Fecha'] <= fecha_corte]
    if not df_historico.empty:
        pv, ev = df_historico.iloc[-1]['Porcentaje_Planificado'], df_historico.iloc[-1]['Porcentaje_Fisico']
    else:
        pv = ev = 0.0
    return pv, ev, ev - pv, (ev / pv if pv > 0 else 0.0)

# ==========================================
# 3. LÓGICA PRINCIPAL Y BARRA LATERAL
# ==========================================

df_tareas, fecha_modificacion = cargar_datos()

if df_tareas.empty:
    st.markdown("<h2 style='text-align: center;'>Panel EVM</h2>", unsafe_allow_html=True)
    st.warning("No se encontró la base consolidada de tareas. Ejecuta primero tu script de extracción.")
    st.stop()

# Definimos variables globales importantes
fecha_inicio_proyecto = datetime(2026, 7, 13).date()
fecha_hoy = datetime.today().date()
max_fecha_plan = pd.to_datetime(df_tareas['Fin_Planificado'].max()).date() if not df_tareas['Fin_Planificado'].isna().all() else fecha_inicio_proyecto
max_fecha_real = pd.to_datetime(df_tareas['Fin_Real'].max()).date() if not df_tareas['Fin_Real'].isna().all() else fecha_inicio_proyecto
max_date = max(max_fecha_plan, max_fecha_real, fecha_hoy)

# Lista Maestra de Contratistas

with st.sidebar:
    st.markdown("<h3><i class='fas fa-sliders-h' style='color:#1f77b4; margin-right: 8px;'></i>Control y Seguimiento</h3>", unsafe_allow_html=True)
    st.caption(f"<i class='fas fa-database' style='margin-right: 5px;'></i> Base: {fecha_modificacion}", unsafe_allow_html=True)
    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
    
   # 3.1 Filtro Principal Consolidado (Dinámico según subcadena "CONT")
    deptos_unicos = sorted(df_tareas['Departamento'].dropna().unique().tolist())
    
    # Creamos listas derivadas para los grupos
    deptos_contratistas = [d for d in deptos_unicos if "CONT-" in d.upper()]
    deptos_planta = [d for d in deptos_unicos if "CONT-" not in d.upper()]
    
    lista_opciones = ["GENERAL", "CONTRATISTAS", "PLANTA"] + deptos_unicos
    depto_seleccionado = st.selectbox("Departamento / Proyecto", lista_opciones, index=0)
    
    # 3.2 Frecuencia de Control
    frecuencia = st.selectbox("Frecuencia de Control", ["Diario", "Semanal", "Mensual", "Período Completo"], index=0)
    
    if frecuencia == "Diario":
        fecha_corte = st.date_input("Fecha de Corte", value=fecha_hoy)
        inicio_periodo = fecha_corte
        etiqueta_periodo = "el día"
    elif frecuencia == "Semanal":
        diferencia_dias_total = (max_date - fecha_inicio_proyecto).days
        opciones_semanas = [f"Semana {i}" for i in range(1, max(1, (diferencia_dias_total // 7) + 2) + 1)]
        semana_actual_num = max(1, ((fecha_hoy - fecha_inicio_proyecto).days // 7) + 1)
        semana_seleccionada = st.selectbox("Semana de Auditoría", opciones_semanas, index=min(semana_actual_num - 1, len(opciones_semanas) - 1))
        inicio_periodo = fecha_inicio_proyecto + timedelta(weeks=int(semana_seleccionada.split(" ")[1]) - 1)
        fecha_corte = inicio_periodo + timedelta(days=6)
        etiqueta_periodo = "la semana"
    elif frecuencia == "Mensual":
        meses = []
        fecha_temp = fecha_inicio_proyecto
        mes_contador = 1
        while fecha_temp <= max_date:
            nombre_mes = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][fecha_temp.month - 1]
            meses.append({"label": f"Mes {mes_contador} ({nombre_mes} {fecha_temp.year})", "year": fecha_temp.year, "month": fecha_temp.month})
            _, ult_dia = calendar.monthrange(fecha_temp.year, fecha_temp.month)
            fecha_temp = (fecha_temp.replace(day=1) + timedelta(days=32)).replace(day=1)
            mes_contador += 1
            
        opciones_meses = [m['label'] for m in meses]
        idx_mes_actual = next((i for i, m in enumerate(meses) if m['year'] == fecha_hoy.year and m['month'] == fecha_hoy.month), 0)
        mes_seleccionado = st.selectbox("Mes de Auditoría", opciones_meses, index=idx_mes_actual)
        mes_data = next(m for m in meses if m['label'] == mes_seleccionado)
        _, ult_dia = calendar.monthrange(mes_data['year'], mes_data['month'])
        fecha_corte = datetime(mes_data['year'], mes_data['month'], ult_dia).date()
        inicio_periodo = fecha_inicio_proyecto if mes_data['label'] == meses[0]['label'] else datetime(mes_data['year'], mes_data['month'], 1).date()
        etiqueta_periodo = "el mes"
    elif frecuencia == "Período Completo":
        st.info(f"Análisis hasta el {max_date.strftime('%d/%m/%Y')}")
        fecha_corte = max_date
        inicio_periodo = fecha_inicio_proyecto
        etiqueta_periodo = "el proyecto"

# 3.3 Lógica de Filtrado del DataFrame
if depto_seleccionado == "GENERAL":
    df_filtrado = df_tareas.copy()
elif depto_seleccionado == "CONTRATISTAS":
    df_filtrado = df_tareas[df_tareas['Departamento'].str.startswith('CONT-', na=False)].copy()
elif depto_seleccionado == "PLANTA":
    df_filtrado = df_tareas[~df_tareas['Departamento'].str.startswith('CONT-', na=False)].copy()
else:
    df_filtrado = df_tareas[df_tareas['Departamento'] == depto_seleccionado].copy()

# 3.4 Procesamiento Curvas S y KPIs
df_curvas = procesar_serie_tiempo_evm(df_filtrado, fecha_corte)
pv_val, ev_val, sv_val, spi_val = calcular_kpis_a_la_fecha(df_curvas, fecha_corte)
# Cálculo de KPI Estático sin dilución
peso_total_filtro = df_filtrado['Duracion_Dias'].sum()
if peso_total_filtro == 0: peso_total_filtro = 1

# Multiplicamos el peso de cada tarea por su avance real y sumamos el total
ev_real_acumulado = (pd.to_numeric(df_filtrado['Avance_Fisico_Pct'], errors='coerce').fillna(0) / 100 * df_filtrado['Duracion_Dias']).sum()
ev_real_pct = ev_real_acumulado / peso_total_filtro

tareas_sin_lb = df_filtrado[['Inicio_Planificado', 'Fin_Planificado']].isna().any(axis=1).sum()

texto_corte = f"Corte al {fecha_corte.strftime('%d/%m/%Y')}"
if frecuencia == "Semanal": texto_corte = f"Corte: {semana_seleccionada} ({fecha_corte.strftime('%d/%m/%Y')})"
elif frecuencia == "Mensual": texto_corte = f"Corte: {mes_seleccionado} ({fecha_corte.strftime('%d/%m/%Y')})"

# ==========================================
# 4. RENDERIZADO DEL DASHBOARD (LAYOUT ASIMÉTRICO)
# ==========================================

st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
    <h2 style="margin: 0 !important; padding: 0 !important;"><i class='fas fa-industry' style='color:#1f77b4; margin-right: 10px;'></i>{depto_seleccionado} <span style='font-size: 13px; font-weight: normal; color: gray; margin-left: 10px;'>| {texto_corte}</span></h2>
    <div style="background-color: rgba(44, 160, 44, 0.08); border: 1px solid #2ca02c; padding: 6px 16px; border-radius: 6px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <span style="font-size: 11px; font-weight: 700; color: #2ca02c; text-transform: uppercase; letter-spacing: 0.5px;">EV Real Acumulado (Hoy)</span><br>
        <span style="font-size: 24px; font-weight: bold; color: #2ca02c; line-height: 1.1;">{ev_real_pct*100:.1f}%</span>
    </div>
</div>
""", unsafe_allow_html=True)
if tareas_sin_lb > 0: st.warning(f"Alerta: {tareas_sin_lb} tareas sin línea base distorsionando PV.")

# --- CUADRÍCULA PRINCIPAL (75% Izq / 25% Der) ---
col_main, col_right = st.columns([7.5, 2.5], gap="large")

with col_main:
    # 1. ENCABEZADO PRINCIPAL Y KPIs
    header_row = st.columns([3, 1.2, 1.2, 1.2, 1.2])
    
    with header_row[0]:
        titulo_seccion = "Visión de Control y Seguimiento" if depto_seleccionado in ["GENERAL", "CONTRATISTAS", "PLANTA"] else "Análisis de Eficiencia"
        st.markdown(f"<h5 style='padding-top: 10px;'><i class='fas fa-chart-line' style='color:#7f7f7f; margin-right: 8px;'></i>{titulo_seccion}</h5>", unsafe_allow_html=True)
        
    with header_row[1]: st.metric("Planificado (PV)", f"{pv_val*100:.1f}%")
    with header_row[2]: st.metric("Ganado (EV)", f"{ev_val*100:.1f}%", f"{sv_val*100:.1f}% SV", delta_color="normal" if sv_val >= 0 else "inverse")
    with header_row[3]: st.metric("Variación (SV)", f"{sv_val*100:.1f}%", "Adelantado" if sv_val >= 0 else "Atrasado", delta_color="normal" if sv_val >= 0 else "inverse")
    with header_row[4]: st.metric("Eficiencia (SPI)", f"{spi_val:.2f}", "Eficiente" if spi_val >= 1.0 else "Deficiente", delta_color="normal" if spi_val >= 1.0 else "inverse")

    st.markdown("<hr style='margin-top: 5px;'>", unsafe_allow_html=True)

    # 2. MAIN CHART AREA (Muestra gráfica comparativa para Grupos Lógicos)
    if depto_seleccionado in ["GENERAL", "CONTRATISTAS", "PLANTA"]:
        tipo_grafico = st.radio("Visualización:", ["Barras Horizontales", "Líneas con Marcadores"], horizontal=True, label_visibility="collapsed")
        
        datos_comparativa = [{"Departamento": f"TOTAL {depto_seleccionado}", "PV (%)": pv_val * 100, "EV (%)": ev_val * 100}]
        
        # Filtramos qué departamentos evaluar usando las listas generadas en la barra lateral
        if depto_seleccionado == "GENERAL":
            deptos_a_comparar = deptos_unicos
        elif depto_seleccionado == "CONTRATISTAS":
            deptos_a_comparar = deptos_contratistas
        elif depto_seleccionado == "PLANTA":
            deptos_a_comparar = deptos_planta

        for d in deptos_a_comparar:
            df_d = df_tareas[df_tareas['Departamento'] == d].copy()
            if not df_d.empty:
                pv_d, ev_d, _, _ = calcular_kpis_a_la_fecha(procesar_serie_tiempo_evm(df_d, fecha_corte), fecha_corte)
                datos_comparativa.append({"Departamento": d, "PV (%)": pv_d * 100, "EV (%)": ev_d * 100})
            
        # 1. Creamos el DataFrame base y separamos el Total de los Departamentos
        df_bruto = pd.DataFrame(datos_comparativa)
        mask_total = df_bruto['Departamento'].str.startswith("TOTAL")
        
        df_total = df_bruto[mask_total]
        df_deptos = df_bruto[~mask_total].sort_values(by="EV (%)", ascending=True)
        
        fig_comp = go.Figure()
        
        if tipo_grafico == "Barras Horizontales":
            # Para que quede al FONDO, el Total debe ser el índice 0
            df_comp = pd.concat([df_total, df_deptos])
            
            fig_comp.add_trace(go.Bar(y=df_comp['Departamento'], x=df_comp['PV (%)'], orientation='h', name='PV %', marker_color='#1f77b4', text=df_comp['PV (%)'].apply(lambda val: f"{val:.1f}%"), textposition='auto'))
            fig_comp.add_trace(go.Bar(y=df_comp['Departamento'], x=df_comp['EV (%)'], orientation='h', name='EV %', marker_color='#2ca02c', text=df_comp['EV (%)'].apply(lambda val: f"{val:.1f}%"), textposition='auto'))
            fig_comp.update_layout(barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=380, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        
        else:
            # Para que quede a la DERECHA, el Total debe ir al final
            df_comp = pd.concat([df_deptos, df_total])
            
            fig_comp.add_trace(go.Scatter(x=df_comp['Departamento'], y=df_comp['PV (%)'], mode='lines+markers', name='PV %', line=dict(color='#1f77b4', width=3, dash='dash'), marker=dict(size=10)))
            fig_comp.add_trace(go.Scatter(x=df_comp['Departamento'], y=df_comp['EV (%)'], mode='lines+markers', name='EV %', line=dict(color='#2ca02c', width=3), marker=dict(size=10)))
            fig_comp.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=380, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            
        st.plotly_chart(fig_comp, use_container_width=True)
    
    else:
        # Pestañas para el Departamento Específico (Top 10 vs SPI Histórico)
        tab1, tab2 = st.tabs(["📉 Evolución de Eficiencia (SPI)", "📋 Top 10 Tareas Críticas"])
        
        with tab1:
            df_hist_spi = df_curvas[df_curvas['Fecha'] <= fecha_corte].copy()
            df_hist_spi['SPI_Hist'] = df_hist_spi['Porcentaje_Fisico'] / df_hist_spi['Porcentaje_Planificado'].replace(0, pd.NA)
            df_hist_spi['SPI_Hist'] = df_hist_spi['SPI_Hist'].fillna(0)
            
            fig_spi = go.Figure()
            fig_spi.add_trace(go.Scatter(x=df_hist_spi['Fecha'], y=df_hist_spi['SPI_Hist'], mode='lines+markers', name='SPI', line=dict(color='#1f77b4', width=3), marker=dict(size=6)))
            fig_spi.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Límite Eficiente (1.0)", annotation_position="bottom right")
            fig_spi.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=340, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Índice SPI")
            st.plotly_chart(fig_spi, use_container_width=True)
            
        with tab2:
            df_top = df_filtrado.copy()
            corte_ts_grafico = pd.Timestamp(fecha_corte)
            
            def calc_pv_task(row):
                if pd.isna(row['Inicio_Planificado']) or pd.isna(row['Fin_Planificado']): return 0.0
                if corte_ts_grafico >= row['Fin_Planificado']: return 100.0
                if corte_ts_grafico <= row['Inicio_Planificado']: return 0.0
                total_days = (row['Fin_Planificado'] - row['Inicio_Planificado']).days + 1
                elapsed = (corte_ts_grafico - row['Inicio_Planificado']).days + 1
                return (elapsed / total_days) * 100.0

            def calc_ev_task(row):
                if pd.isna(row['Inicio_Real']) or row['Inicio_Real'] > corte_ts_grafico: return 0.0
                return float(row['Avance_Fisico_Pct']) if pd.notna(row['Avance_Fisico_Pct']) else 0.0
                
            df_top['PV_Task'] = df_top.apply(calc_pv_task, axis=1)
            df_top['EV_Task'] = df_top.apply(calc_ev_task, axis=1)
            df_top = df_top.sort_values(by='Duracion_Dias', ascending=False).head(10).sort_values(by='Duracion_Dias', ascending=True)
            
            fig_top = go.Figure()
            nombres_cortos = df_top['Nombre'].apply(lambda x: (x[:45] + '..') if len(x) > 45 else x)
            fig_top.add_trace(go.Bar(y=nombres_cortos, x=df_top['PV_Task'], orientation='h', name='PV %', marker_color='#1f77b4', text=df_top['PV_Task'].apply(lambda val: f"{val:.1f}%"), textposition='auto'))
            fig_top.add_trace(go.Bar(y=nombres_cortos, x=df_top['EV_Task'], orientation='h', name='EV %', marker_color='#2ca02c', text=df_top['EV_Task'].apply(lambda val: f"{val:.1f}%"), textposition='auto'))
            fig_top.update_layout(barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=340, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_top, use_container_width=True)

    st.markdown("<hr style='margin-top: 5px;'>", unsafe_allow_html=True)

    # 3. SECCIÓN INFERIOR: Tarjetas de Estado Operativo Minimalistas
    st.markdown("<h5><i class='fas fa-cogs' style='color:#7f7f7f; margin-right: 8px;'></i> Diagnóstico Operativo</h5>", unsafe_allow_html=True)
    
    corte_ts, inicio_ts = pd.Timestamp(fecha_corte), pd.Timestamp(inicio_periodo)
    m_t_acum = ((df_filtrado['Fin_Real'] <= corte_ts) & (df_filtrado['Avance_Fisico_Pct'] >= 100)).sum()
    m_t_antes = ((df_filtrado['Fin_Real'] < inicio_ts) & (df_filtrado['Avance_Fisico_Pct'] >= 100)).sum()
    m_t_per = ((df_filtrado['Fin_Real'] >= inicio_ts) & (df_filtrado['Fin_Real'] <= corte_ts) & (df_filtrado['Avance_Fisico_Pct'] >= 100)).sum()
    m_e = ((df_filtrado['Inicio_Real'] <= corte_ts) & (df_filtrado['Avance_Fisico_Pct'] < 100)).sum()
    m_e_antes = ((df_filtrado['Inicio_Real'] < inicio_ts) & (df_filtrado['Avance_Fisico_Pct'] < 100)).sum()
    
    m_tr_per = ((df_filtrado['Inicio_Real'] <= corte_ts) & (df_filtrado['Fin_Real'].isna() | (df_filtrado['Fin_Real'] >= inicio_ts))).sum()
    m_atr = ((df_filtrado['Inicio_Planificado'] <= corte_ts) & (df_filtrado['Inicio_Real'].isna() | (df_filtrado['Inicio_Real'] > corte_ts))).sum()
    m_inc = ((df_filtrado['Fin_Planificado'] >= inicio_ts) & (df_filtrado['Fin_Planificado'] <= corte_ts) & (df_filtrado['Avance_Fisico_Pct'] < 100)).sum()
    m_v_acum = ((df_filtrado['Fin_Planificado'] <= corte_ts) & (df_filtrado['Avance_Fisico_Pct'] < 100)).sum()

    o1, o2, o3, o4, o5 = st.columns(5)
    with o1: st.markdown(card_html("Term. (Total)", m_t_acum, "fas fa-check-double", "blue"), unsafe_allow_html=True)
    with o2: st.markdown(card_html("Term. Antes", m_t_antes, "fas fa-clock-rotate-left", "blue"), unsafe_allow_html=True)
    with o3: st.markdown(card_html(f"Terminadas", m_t_per, "fas fa-check-circle", "green"), unsafe_allow_html=True)
    with o4: st.markdown(card_html("Activas", m_e, "fas fa-rocket", "blue"), unsafe_allow_html=True)
    with o5: st.markdown(card_html("Arrastrada", m_e_antes, "fas fa-history", "blue"), unsafe_allow_html=True)
    
    o6, o7, o8, o9, o10 = st.columns(5)
    with o6: st.markdown(card_html(f"Trabajadas", m_tr_per, "fas fa-calendar-day", "gray"), unsafe_allow_html=True)
    with o7: st.markdown(card_html("No Inic.", m_atr, "fas fa-pause-circle", "orange"), unsafe_allow_html=True)
    with o8: st.markdown(card_html(f"Incumplidas", m_inc, "fas fa-times-circle", "red"), unsafe_allow_html=True)
    with o9: st.markdown(card_html("Vencidas", m_v_acum, "fas fa-calendar-xmark", "red"), unsafe_allow_html=True)
    with o10: st.markdown(card_html("Sin L. Base", tareas_sin_lb, "fas fa-triangle-exclamation", "red"), unsafe_allow_html=True)

with col_right:
    # 3. COLUMNA DERECHA (Curva S, Variación y Notepad)
    fecha_str = fecha_corte.strftime('%Y-%m-%d')
    
    st.markdown("<h5><i class='fas fa-chart-area' style='color:#7f7f7f; margin-right: 8px;'></i> Curva S</h5>", unsafe_allow_html=True)
    if not df_curvas.empty:
        fig_s = go.Figure()
        fig_s.add_trace(go.Scatter(x=df_curvas['Fecha'], y=df_curvas['Porcentaje_Planificado'] * 100, mode='lines', name='PV', line=dict(color='#1f77b4', width=3, dash='dash')))
        fig_s.add_trace(go.Scatter(x=df_curvas['Fecha'], y=df_curvas['Porcentaje_Fisico'] * 100, mode='lines', name='EV', line=dict(color='#2ca02c', width=3)))
        fig_s.add_vline(x=fecha_str, line_width=2, line_dash="dot", line_color="red")
        fig_s.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_s, use_container_width=True)

    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)

    st.markdown("<h5><i class='fas fa-chart-bar' style='color:#7f7f7f; margin-right: 8px;'></i> Variación (SV)</h5>", unsafe_allow_html=True)
    if not df_curvas.empty:
        fig_sv = go.Figure()
        fig_sv.add_trace(go.Bar(x=df_curvas['Fecha'], y=df_curvas['SV_Porcentaje'], name='SV %', marker_color=['#d62728' if val < 0 else '#2ca02c' for val in df_curvas['SV_Porcentaje']]))
        fig_sv.add_vline(x=fecha_str, line_width=2, line_dash="dot", line_color="red")
        fig_sv.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_sv, use_container_width=True)
        
    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
    
    # Notepad Nativo
    st.markdown("<h5><i class='fas fa-edit' style='color:#7f7f7f; margin-right: 8px;'></i>Notas</h5>", unsafe_allow_html=True)
    st.text_area("Comentarios del turno", placeholder="Escribe justificaciones o notas de retraso aquí...", label_visibility="collapsed")


# --- SECCIÓN FINAL: Data Analítica Expansible ---
st.markdown("---")
st.markdown("<h5><i class='fas fa-table' style='color:#7f7f7f; margin-right: 8px;'></i> Sección de Datos Analíticos</h5>", unsafe_allow_html=True)

with st.expander("Tabla de Datos Procesados y Desempeño"):
    df_hist = df_curvas[df_curvas['Fecha'] <= fecha_corte].copy()
    if not df_hist.empty:
        df_hist['Fecha_DT'] = pd.to_datetime(df_hist['Fecha'])
        
        if frecuencia == "Diario":
            df_hist['Periodo'] = df_hist['Fecha_DT'].dt.strftime('%d/%m/%Y')
            df_grp = df_hist.copy()
            df_grp['PV (%)'] = df_grp['Porcentaje_Planificado'] * 100
            df_grp['EV (%)'] = df_grp['Porcentaje_Fisico'] * 100
            df_grp['SV (%)'] = df_grp['SV_Porcentaje']
            df_grp['SPI'] = df_grp['EV (%)'] / df_grp['PV (%)'].replace(0, pd.NA)
            df_grp = df_grp.sort_values(by='Fecha_DT', ascending=False)
            
        elif frecuencia == "Semanal":
            df_hist['Lunes_Inicio'] = df_hist['Fecha_DT'] - pd.to_timedelta(df_hist['Fecha_DT'].dt.weekday, unit='d')
            df_hist['Domingo_Fin'] = df_hist['Lunes_Inicio'] + pd.Timedelta(days=6)
            df_hist['Periodo'] = df_hist['Lunes_Inicio'].dt.strftime('%d/%m/%Y') + " al " + df_hist['Domingo_Fin'].dt.strftime('%d/%m/%Y')
            df_grp = df_hist.groupby('Periodo').agg(PV_Max=('Porcentaje_Planificado', 'max'), EV_Max=('Porcentaje_Fisico', 'max'), SV_Last=('SV_Porcentaje', 'last'), Fecha_Sort=('Lunes_Inicio', 'first')).reset_index()
            df_grp['PV (%)'] = df_grp['PV_Max'] * 100
            df_grp['EV (%)'] = df_grp['EV_Max'] * 100
            df_grp['SV (%)'] = df_grp['SV_Last']
            df_grp['SPI'] = df_grp['EV (%)'] / df_grp['PV (%)'].replace(0, pd.NA)
            df_grp = df_grp.sort_values(by='Fecha_Sort', ascending=False)
            
        elif frecuencia in ["Mensual", "Período Completo"]:
            df_hist['Periodo'] = df_hist['Fecha_DT'].dt.strftime('%Y-%m')
            df_grp = df_hist.groupby('Periodo').agg(PV_Max=('Porcentaje_Planificado', 'max'), EV_Max=('Porcentaje_Fisico', 'max'), SV_Last=('SV_Porcentaje', 'last'), Fecha_Sort=('Fecha_DT', 'max')).reset_index()
            df_grp['PV (%)'] = df_grp['PV_Max'] * 100
            df_grp['EV (%)'] = df_grp['EV_Max'] * 100
            df_grp['SV (%)'] = df_grp['SV_Last']
            df_grp['SPI'] = df_grp['EV (%)'] / df_grp['PV (%)'].replace(0, pd.NA)
            df_grp = df_grp.sort_values(by='Fecha_Sort', ascending=False)
            
        df_grp['SPI'] = df_grp['SPI'].fillna(0)
        
        st.dataframe(
            df_grp[['Periodo', 'PV (%)', 'EV (%)', 'SV (%)', 'SPI']], use_container_width=True,
            column_config={
                "Periodo": "Período",
                "PV (%)": st.column_config.NumberColumn("Planificado Acumulado (%)", format="%.2f %%"),
                "EV (%)": st.column_config.NumberColumn("Real Acumulado (%)", format="%.2f %%"),
                "SV (%)": st.column_config.NumberColumn("Variación (SV %)", format="%.2f %%"),
                "SPI": st.column_config.NumberColumn("Eficiencia (SPI)", format="%.2f")
            }
        )

with st.expander("Inspeccionar Tabla Cruda de Tareas"):
    st.dataframe(df_filtrado[['ID_Tarea', 'Nombre', 'Avance_Fisico_Pct', 'Inicio_Planificado', 'Fin_Planificado', 'Fin_Real']], use_container_width=True)