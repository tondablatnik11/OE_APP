import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
from datetime import datetime, timedelta

# --- 1. KONFIGURACE ---
st.set_page_config(page_title="Logistics Performance Analyzer", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    h1, h2, h3 { color: #58a6ff !important; font-family: 'Inter', sans-serif; }
    .stMetric { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. POMOCNÉ FUNKCE ---
def parse_time_duration(val):
    """Převede různé formáty času (HH:MM:SS, nebo datetime) na minuty (float)."""
    if pd.isna(val) or val == "":
        return None
    
    # Pokud je to už datetime objekt (např. z Excelu)
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.hour * 60 + val.minute + val.second / 60
    
    # Pokud je to string
    val = str(val).strip()
    try:
        # Zkus formát HH:MM:SS nebo HH:MM
        parts = val.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except:
        return None
    return None

def clean_time_string(t_str):
    """Opraví časový string pro výpočty."""
    if pd.isna(t_str): return None
    t_str = str(t_str).strip()
    # Pokud Excel udělal z času datum (např. 1900-01-01 14:00:00)
    if " " in t_str:
        t_str = t_str.split(" ")[1]
    return t_str

# --- 3. APLIKACE ---
st.title("📈 Logistics Performance Analyzer")
st.markdown("Detailní analýza výkonnosti balení, časů a materiálů.")

# SIDEBAR
with st.sidebar:
    st.header("Vstupní data")
    uploaded_file = st.file_uploader("1. Hlavní data (All.csv / Excel)", type=['csv', 'xlsx'])
    breaks_file = st.file_uploader("2. Přestávky (Breaks.csv) - Volitelné", type=['csv', 'xlsx'])
    
    st.markdown("---")
    st.caption("Verze 2.0 | Performance Focus")

if uploaded_file:
    try:
        # NAČTENÍ DAT
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        # Normalizace názvů sloupců (aby to fungovalo pro různé verze souborů)
        # Zkusíme najít klíčové sloupce, i když se jmenují trochu jinak
        cols_map = {
            col: col for col in df.columns
        }
        # Hledání "Process Time - cleaned" nebo "Process Time"
        time_col = None
        for c in df.columns:
            if "cleaned" in c.lower() and "time" in c.lower():
                time_col = c
                break
        if not time_col:
            for c in df.columns:
                if "process time" in c.lower():
                    time_col = c
                    break
        
        # PŘÍPRAVA DAT
        # 1. Čas trvání (Duration) v minutách
        if time_col:
            df['Duration_Min'] = df[time_col].apply(parse_time_duration)
        else:
            # Pokud není sloupec s trváním, zkusíme vypočítat z START a END
            st.warning("Nenalezen sloupec 'Process Time', počítám z 'START' a 'END'.")
            # (Zde by byla logika pro výpočet Start-End, pro teď předpokládáme, že Process Time existuje dle tvých dat)
            df['Duration_Min'] = 0

        # Odstranění řádků bez času (chyby)
        df = df[df['Duration_Min'] > 0].copy()

        # 2. Počty kusů
        qty_col = 'Number of pieces' if 'Number of pieces' in df.columns else df.columns[df.columns.str.contains('pieces')][0]
        df['Pieces'] = pd.to_numeric(df[qty_col], errors='coerce').fillna(0)
        
        # 3. Čas na 1 kus
        df['Min_per_Piece'] = df['Duration_Min'] / df['Pieces']
        # Ošetření dělení nulou
        df.loc[df['Pieces'] == 0, 'Min_per_Piece'] = 0

        # 4. Hodina začátku (pro časovou osu)
        start_col = 'START' if 'START' in df.columns else df.columns[df.columns.str.contains('START', case=False)][0]
        df['Start_Hour'] = df[start_col].astype(str).apply(lambda x: clean_time_string(x).split(':')[0] if clean_time_string(x) and ':' in clean_time_string(x) else '00').astype(int)

        # --- DASHBOARD ---
        
        # 1. HLAVNÍ METRIKY
        st.subheader("🚀 Celková produktivita")
        col1, col2, col3, col4 = st.columns(4)
        
        avg_order_time = df['Duration_Min'].mean()
        avg_piece_time = df['Min_per_Piece'].mean() # Průměr průměrů
        # Nebo lépe: Celkový čas / Celkové kusy (vážený průměr)
        weighted_avg_piece_time = df['Duration_Min'].sum() / df['Pieces'].sum()

        col1.metric("Ø Čas na Zakázku", f"{avg_order_time:.1f} min")
        col2.metric("Ø Čas na 1 Kus", f"{weighted_avg_piece_time:.2f} min")
        col3.metric("Celkem Zakázek", len(df))
        col4.metric("Celkem Kusů", f"{df['Pieces'].sum():,.0f}")

        st.divider()

        # 2. ANALÝZA ARTIKLŮ (MATERIAL)
        st.subheader("📦 Analýza Materiálů (Top 15 nejpomalejších)")
        st.caption("Které materiály trvá zabalit nejdéle (v průměru na 1 kus)?")
        
        mat_stats = df.groupby('Material').agg({
            'Duration_Min': 'mean',         # Průměrný čas na zakázku
            'Min_per_Piece': 'mean',        # Průměrný čas na kus
            'DN NUMBER (SAP)': 'count',     # Počet zakázek
            'Pieces': 'sum'                 # Celkem kusů
        }).reset_index()
        
        # Filtr: Bereme jen materiály, co se dělaly alespoň 3x (aby to nezkreslila jedna chyba)
        mat_stats_filtered = mat_stats[mat_stats['DN NUMBER (SAP)'] >= 3]
        
        # Seřazení podle času na kus
        top_slowest = mat_stats_filtered.sort_values(by='Min_per_Piece', ascending=False).head(15)
        
        st.dataframe(
            top_slowest, 
            column_config={
                "Material": "Materiál",
                "Duration_Min": st.column_config.NumberColumn("Ø Čas Zakázka (min)", format="%.1f"),
                "Min_per_Piece": st.column_config.NumberColumn("Ø Čas/Kus (min)", format="%.2f"),
                "DN NUMBER (SAP)": st.column_config.NumberColumn("Počet zakázek"),
                "Pieces": st.column_config.NumberColumn("Celkem kusů")
            },
            use_container_width=True,
            hide_index=True
        )

        col_l, col_r = st.columns(2)
        
        # 3. ZÁKAZNÍCI (Scatter Plot)
        with col_l:
            st.subheader("👥 Analýza Zákazníků")
            cust_stats = df.groupby('CUSTOMER').agg({
                'DN NUMBER (SAP)': 'count',
                'Duration_Min': 'sum'
            }).reset_index()
            cust_stats.columns = ['Zákazník', 'Počet Zakázek', 'Celkový Čas (min)']
            
            # Graf
            fig_cust = px.scatter(cust_stats, x='Počet Zakázek', y='Celkový Čas (min)', 
                                  size='Celkový Čas (min)', hover_name='Zákazník', text='Zákazník',
                                  title="Zákazníci: Počet zakázek vs. Celkový čas",
                                  color='Celkový Čas (min)', color_continuous_scale='Bluered')
            fig_cust.update_traces(textposition='top center')
            st.plotly_chart(fig_cust, use_container_width=True)

        # 4. OBALOVÝ MATERIÁL
        with col_r:
            st.subheader("📦 Využití Obalů")
            # Součet sloupců s obaly
            pack_sums = {
                'Palety': df['Number of pallets'].sum() if 'Number of pallets' in df.columns else 0,
                'KLT': df['Number of KLTs'].sum() if 'Number of KLTs' in df.columns else 0,
                'Kartony': df['Cartons'].sum() if 'Cartons' in df.columns else 0 # Nutno ověřit název sloupce v tvém CSV
            }
            # Pokud sloupec Cartons není, zkusíme ho najít
            if pack_sums['Kartony'] == 0:
                 # Hledáme sloupec co obsahuje 'carton' nebo 'box'
                 carton_cols = [c for c in df.columns if 'carton' in c.lower()]
                 if carton_cols:
                     pack_sums['Kartony'] = df[carton_cols[0]].sum()

            pack_df = pd.DataFrame(list(pack_sums.items()), columns=['Typ', 'Počet'])
            fig_pack = px.pie(pack_df, values='Počet', names='Typ', title="Podíl použitých obalových jednotek", hole=0.4)
            st.plotly_chart(fig_pack, use_container_width=True)

        st.divider()

        # 5. ČASOVÁ OSA (Špičky)
        st.subheader("⏰ Vytížení v průběhu dne")
        hourly_counts = df.groupby('Start_Hour')['DN NUMBER (SAP)'].count().reset_index()
        hourly_counts.columns = ['Hodina', 'Počet Zakázek']
        
        fig_timeline = px.bar(hourly_counts, x='Hodina', y='Počet Zakázek', 
                              title="Počet zahájených zakázek dle hodiny",
                              color='Počet Zakázek', color_continuous_scale='Viridis')
        fig_timeline.update_layout(xaxis=dict(tickmode='linear', dtick=1))
        st.plotly_chart(fig_timeline, use_container_width=True)

        # 6. KORELACE (Bonus)
        st.subheader("🔍 Detail: Kusy vs. Čas (Hledání anomálií)")
        st.caption("Každý bod je jedna zakázka. Body vysoko vlevo jsou 'pomalé' zakázky (málo kusů, hodně času).")
        fig_corr = px.scatter(df, x='Pieces', y='Duration_Min', 
                              hover_data=['Material', 'CUSTOMER', 'DN NUMBER (SAP)'],
                              color='Duration_Min', opacity=0.6,
                              labels={'Pieces': 'Počet Kusů', 'Duration_Min': 'Čas (min)'})
        st.plotly_chart(fig_corr, use_container_width=True)

        # --- EXPORT ---
        st.subheader("📥 Export Dat")
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # Sheet 1: Data pro Pivoty
            df.to_excel(writer, sheet_name='Clean_Data', index=False)
            
            # Sheet 2: Material Stats
            mat_stats.sort_values(by='Duration_Min', ascending=False).to_excel(writer, sheet_name='Material_Analysis', index=False)
            
            # Sheet 3: Customer Stats
            cust_stats.sort_values(by='Celkový Čas (min)', ascending=False).to_excel(writer, sheet_name='Customer_Analysis', index=False)
            
            # Auto-adjust columns
            worksheet = writer.sheets['Clean_Data']
            worksheet.set_column(0, len(df.columns), 15)

        st.download_button(
            label="Stáhnout Analytický Excel (.xlsx)",
            data=buffer.getvalue(),
            file_name="Logistics_Analysis_Report.xlsx",
            mime="application/vnd.ms-excel"
        )

    except Exception as e:
        st.error(f"Chyba při zpracování dat: {e}")
        st.warning("Zkontrolujte, zda soubor obsahuje sloupce jako 'Material', 'CUSTOMER', 'START', 'Process Time' atd.")

else:
    st.info("Nahrajte soubor s daty (All.csv nebo Excel) pro zobrazení dashboardu.")
