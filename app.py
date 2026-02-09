import streamlit as st
import pandas as pd
import plotly.express as px
import io
from datetime import datetime, time

# --- 1. KONFIGURACE ---
st.set_page_config(page_title="Logistics Perf. Analyzer v2.2", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    h1, h2, h3 { color: #58a6ff !important; font-family: 'Inter', sans-serif; }
    .stMetric { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ROBUSTNÍ FUNKCE PRO ČAS ---
def parse_time_to_minutes(val):
    """Převede jakýkoliv formát času na minuty (int)."""
    if pd.isna(val) or val == "":
        return None
    
    # 1. Pokud je to datetime/timestamp
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.hour * 60 + val.minute + val.second / 60
    
    # 2. Pokud je to objekt time
    if hasattr(val, 'hour'):
        return val.hour * 60 + val.minute + val.second / 60
    
    # 3. Pokud je to string
    val_str = str(val).strip()
    
    # Oříznutí data (1900-01-01 14:00:00 -> 14:00:00)
    if " " in val_str:
        val_str = val_str.split(" ")[-1]
        
    try:
        parts = val_str.split(':')
        if len(parts) == 3: # HH:MM:SS
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        elif len(parts) == 2: # HH:MM
            return int(parts[0]) * 60 + int(parts[1])
    except:
        return None
    return None

def calculate_duration(row):
    """Vypočítá trvání ze START a END, pokud není Process Time."""
    # Pokud už máme Duration_Min (z Process Time), použijeme to
    if pd.notna(row.get('Duration_Min')) and row['Duration_Min'] > 0:
        return row['Duration_Min']
    
    # Jinak počítáme z Start/End
    s = parse_time_to_minutes(row.get('START'))
    e = parse_time_to_minutes(row.get('END'))
    
    if s is not None and e is not None:
        diff = e - s
        if diff < 0: # Přechod přes půlnoc
            diff += 24 * 60
        return diff
    return None

# --- 3. APLIKACE ---
st.title("📈 Logistics Performance Analyzer v2.2")

with st.sidebar:
    st.header("Vstupní data")
    uploaded_file = st.file_uploader("1. Hlavní data (All.csv / Excel)", type=['csv', 'xlsx'])
    breaks_file = st.file_uploader("2. Přestávky (Breaks.csv)", type=['csv', 'xlsx'])
    st.info("Verze 2.2: Oprava načítání časů a výpočet START/END.")

if uploaded_file:
    try:
        # NAČTENÍ DAT
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        # Očištění názvů sloupců
        df.columns = [str(c).strip() for c in df.columns]

        # --- A. DETEKCE SLOUPCE S ČASEM ---
        # Hledáme sloupec s trváním (Process Time)
        time_col = None
        
        # 1. Zkusíme najít "cleaned" (očištěný čas)
        cleaned_candidates = [c for c in df.columns if "cleaned" in c.lower() and "time" in c.lower()]
        if cleaned_candidates:
            # Ověříme, zda není prázdný!
            if df[cleaned_candidates[0]].notna().sum() > 10: # Alespoň 10 vyplněných řádků
                time_col = cleaned_candidates[0]
                st.success(f"Používám očištěný čas: {time_col}")
        
        # 2. Pokud není cleaned, hledáme obyčejný Process Time
        if not time_col:
            process_candidates = [c for c in df.columns if "process" in c.lower() and "time" in c.lower()]
            if process_candidates:
                time_col = process_candidates[0]
                st.info(f"Používám sloupec: {time_col}")

        # --- B. PŘEVOD ČASŮ ---
        if time_col:
            df['Duration_Min'] = df[time_col].apply(parse_time_to_minutes)
        else:
            df['Duration_Min'] = None # Zatím nic

        # --- C. DOPOČET Z START/END (FALLBACK) ---
        # Pokud chybí sloupec Process Time nebo je řádek prázdný, zkusíme START/END
        if 'START' in df.columns and 'END' in df.columns:
            # Aplikujeme výpočet řádek po řádku
            df['Duration_Min'] = df.apply(calculate_duration, axis=1)
            
            # Kolik jsme jich dopočítali?
            calc_count = df['Duration_Min'].notna().sum()
            if not time_col:
                st.warning(f"Sloupec 'Process Time' nenalezen. Dopočítáno {calc_count} řádků ze START/END.")

        # --- D. FILTRACE A ČIŠTĚNÍ ---
        # Odstraníme řádky, kde se nepovedlo zjistit čas
        df_clean = df[df['Duration_Min'] > 0].copy()
        
        if df_clean.empty:
            st.error("❌ Nepodařilo se načíst žádná data s platným časem.")
            st.write("Zkontrolujte, zda soubor obsahuje sloupce 'Process Time' nebo 'START' a 'END' ve správném formátu.")
            st.write("Nalezené sloupce:", df.columns.tolist())
            st.stop()

        # Počty kusů (Pieces)
        qty_col = None
        possible_qty = [c for c in df.columns if 'piece' in c.lower() or 'kus' in c.lower()]
        if possible_qty:
            qty_col = possible_qty[0]
            df_clean['Pieces'] = pd.to_numeric(df_clean[qty_col], errors='coerce').fillna(0)
        else:
            df_clean['Pieces'] = 1 # Fallback
            st.warning("Nenalezen sloupec 'Number of pieces', počítám 1 kus na zakázku.")

        # Výpočet minuty na kus
        df_clean['Min_per_Piece'] = df_clean['Duration_Min'] / df_clean['Pieces']
        # Fix pro dělení nulou
        df_clean.loc[df_clean['Pieces'] == 0, 'Min_per_Piece'] = 0

        # --- E. DASHBOARD (Zobrazení) ---
        
        # 1. METRIKY
        st.subheader("📊 Přehled Výkonnosti")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ø Čas na Zakázku", f"{df_clean['Duration_Min'].mean():.1f} min")
        
        # Vážený průměr pro čas na kus (přesnější než průměr průměrů)
        total_time = df_clean['Duration_Min'].sum()
        total_pieces = df_clean['Pieces'].sum()
        weighted_avg = total_time / total_pieces if total_pieces > 0 else 0
        
        c2.metric("Ø Čas na 1 Kus", f"{weighted_avg:.2f} min")
        c3.metric("Zpracováno Zakázek", len(df_clean))
        c4.metric("Zpracováno Kusů", f"{int(total_pieces):,}")

        st.divider()

        # 2. TOP MATERIÁLY
        col_mat, col_cust = st.columns(2)
        
        with col_mat:
            st.subheader("🐌 Nejpomalejší Materiály")
            if 'Material' in df_clean.columns:
                mat_grp = df_clean.groupby('Material').agg(
                    Avg_Time_Piece=('Min_per_Piece', 'mean'),
                    Count=('Material', 'count')
                ).reset_index()
                # Filtr: jen ty, co se dělaly alespoň 3x
                mat_grp = mat_grp[mat_grp['Count'] >= 3].sort_values('Avg_Time_Piece', ascending=False).head(10)
                
                fig_mat = px.bar(mat_grp, x='Avg_Time_Piece', y='Material', orientation='h',
                                 title="Průměrný čas na 1 kus (min)",
                                 text_auto='.2f')
                fig_mat.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_mat, use_container_width=True)
            else:
                st.warning("Chybí sloupec 'Material'.")

        # 3. ZÁKAZNÍCI
        with col_cust:
            st.subheader("🏢 Top Zákazníci dle Času")
            cust_col = 'CUSTOMER' if 'CUSTOMER' in df_clean.columns else df_clean.columns[1] # Tip
            cust_grp = df_clean.groupby(cust_col)['Duration_Min'].sum().reset_index().sort_values('Duration_Min', ascending=False).head(10)
            
            fig_cust = px.pie(cust_grp, values='Duration_Min', names=cust_col, hole=0.4,
                              title="Celkový strávený čas (min)")
            st.plotly_chart(fig_cust, use_container_width=True)
            
        # 4. EXPORT
        st.subheader("📥 Export Dat")
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df_clean.to_excel(writer, index=False, sheet_name="Clean_Data")
            if 'Material' in df_clean.columns:
                mat_grp.to_excel(writer, index=False, sheet_name="Top_Materials")
        
        st.download_button("Stáhnout Analýzu (.xlsx)", buffer.getvalue(), "Logistics_Analysis_v2.xlsx")

    except Exception as e:
        st.error(f"Kritická chyba: {e}")
        st.write("Prosím pošlete screenshot chyby, pokud přetrvává.")
