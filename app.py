import streamlit as st
import pandas as pd
import plotly.express as px
import io
from datetime import datetime, time

# --- 1. KONFIGURACE ---
st.set_page_config(page_title="Logistics Perf. Analyzer v2.3", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    h1, h2, h3 { color: #58a6ff !important; font-family: 'Inter', sans-serif; }
    .stMetric { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px; }
    .error-row { background-color: #3d1616; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ROBUSTNÍ FUNKCE PRO ČAS ---
def parse_time_to_minutes(val):
    """Převede jakýkoliv formát času na minuty (int)."""
    if pd.isna(val) or str(val).strip() == "":
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
        # Nahrazení tečky za dvojtečku (pro případy 14.30)
        val_str = val_str.replace('.', ':')
        
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
        # Pokud je čas 0 (start=end), nastavíme 1 minutu (aby nevypadl z průměrů)
        if diff == 0:
            return 1.0 
        return diff
    return None

# --- 3. APLIKACE ---
st.title("📈 Logistics Performance Analyzer v2.3")

with st.sidebar:
    st.header("Vstupní data")
    uploaded_file = st.file_uploader("1. Hlavní data (All.csv / Excel)", type=['csv', 'xlsx'])
    breaks_file = st.file_uploader("2. Přestávky (Breaks.csv)", type=['csv', 'xlsx'])
    st.info("Verze 2.3: Vylepšená diagnostika chybějících časů.")

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
        time_col = None
        # Hledáme cleaned time
        cleaned_candidates = [c for c in df.columns if "cleaned" in c.lower() and "time" in c.lower()]
        if cleaned_candidates and df[cleaned_candidates[0]].notna().sum() > 10:
            time_col = cleaned_candidates[0]
        # Fallback na process time
        if not time_col:
            process_candidates = [c for c in df.columns if "process" in c.lower() and "time" in c.lower()]
            if process_candidates:
                time_col = process_candidates[0]

        # --- B. VÝPOČTY ---
        # 1. Přímý převod existujícího času
        if time_col:
            df['Duration_Min'] = df[time_col].apply(parse_time_to_minutes)
        else:
            df['Duration_Min'] = None 

        # 2. Dopočet z START/END (pokud Process Time chybí nebo je None)
        if 'START' in df.columns and 'END' in df.columns:
            df['Duration_Min'] = df.apply(calculate_duration, axis=1)

        # --- C. DIAGNOSTIKA (PROČ NĚCO CHYBÍ?) ---
        total_rows = len(df)
        valid_rows = df[df['Duration_Min'] > 0]
        invalid_rows = df[ (df['Duration_Min'].isna()) | (df['Duration_Min'] <= 0) ]
        
        valid_count = len(valid_rows)
        invalid_count = len(invalid_rows)

        # --- D. METRIKY ---
        st.subheader("📊 Přehled Výkonnosti")
        
        # Zobrazení varování, pokud nesedí počty
        if invalid_count > 0:
            st.warning(f"⚠️ Z celkových {total_rows} řádků se u {invalid_count} nepodařilo spočítat čas (chybí START/END nebo Process Time).")
            with st.expander("🔍 Zobrazit řádky s chybou (pro kontrolu)"):
                st.write("Tyto řádky se nezapočítávají do průměrných časů, ale jsou v celkovém počtu zakázek:")
                st.dataframe(invalid_rows[['DN NUMBER (SAP)', 'START', 'END', 'CUSTOMER'] if 'START' in df.columns else invalid_rows.head()])

        c1, c2, c3, c4 = st.columns(4)
        
        # Průměry počítáme jen z platných dat
        avg_duration = valid_rows['Duration_Min'].mean() if valid_count > 0 else 0
        
        # Kusy a vážený průměr
        qty_col = None
        possible_qty = [c for c in df.columns if 'piece' in c.lower() or 'kus' in c.lower()]
        if possible_qty:
            qty_col = possible_qty[0]
            # U invalid řádků nahradíme NaN nulou pro součty
            df['Pieces_Safe'] = pd.to_numeric(df[qty_col], errors='coerce').fillna(0)
            valid_rows = valid_rows.copy() # Avoid SettingWithCopy
            valid_rows['Pieces'] = pd.to_numeric(valid_rows[qty_col], errors='coerce').fillna(0)
        else:
            df['Pieces_Safe'] = 1
            valid_rows['Pieces'] = 1

        total_pieces = df['Pieces_Safe'].sum()
        
        # Vážený průměr času na kus (pouze z řádků, kde známe čas)
        valid_pieces_sum = valid_rows['Pieces'].sum()
        valid_time_sum = valid_rows['Duration_Min'].sum()
        weighted_avg = valid_time_sum / valid_pieces_sum if valid_pieces_sum > 0 else 0

        # Metriky
        c1.metric("Ø Čas na Zakázku", f"{avg_duration:.1f} min")
        c2.metric("Ø Čas na 1 Kus", f"{weighted_avg:.2f} min")
        c3.metric("Celkem Zakázek", f"{total_rows}") # ZDE JE OPRAVA - Zobrazujeme všechny
        c4.metric("Celkem Kusů", f"{int(total_pieces):,}")

        st.divider()

        # --- E. GRAFY (Pouze z validních dat) ---
        if valid_count > 0:
            col_mat, col_cust = st.columns(2)
            
            with col_mat:
                st.subheader("🐌 Nejpomalejší Materiály")
                valid_rows['Min_per_Piece'] = valid_rows['Duration_Min'] / valid_rows['Pieces'].replace(0, 1)
                
                if 'Material' in valid_rows.columns:
                    mat_grp = valid_rows.groupby('Material').agg(
                        Avg_Time_Piece=('Min_per_Piece', 'mean'),
                        Count=('Material', 'count')
                    ).reset_index()
                    mat_grp = mat_grp[mat_grp['Count'] >= 3].sort_values('Avg_Time_Piece', ascending=False).head(10)
                    
                    fig_mat = px.bar(mat_grp, x='Avg_Time_Piece', y='Material', orientation='h',
                                     title="Průměrný čas na 1 kus (min)", text_auto='.2f')
                    fig_mat.update_layout(yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_mat, use_container_width=True)

            with col_cust:
                st.subheader("🏢 Top Zákazníci dle Času")
                cust_col = 'CUSTOMER' if 'CUSTOMER' in valid_rows.columns else valid_rows.columns[1]
                cust_grp = valid_rows.groupby(cust_col)['Duration_Min'].sum().reset_index().sort_values('Duration_Min', ascending=False).head(10)
                
                fig_cust = px.pie(cust_grp, values='Duration_Min', names=cust_col, hole=0.4, title="Celkový strávený čas (min)")
                st.plotly_chart(fig_cust, use_container_width=True)
        
        # --- F. EXPORT ---
        st.subheader("📥 Export Dat")
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # Exportujeme VŠECHNA data, přidáme sloupec s vypočteným časem (kde to šlo)
            df_export = df.copy()
            df_export.to_excel(writer, index=False, sheet_name="All_Data_Calculated")
            
            if valid_count > 0 and 'Material' in valid_rows.columns:
                 mat_grp.to_excel(writer, index=False, sheet_name="Top_Materials")
        
        st.download_button("Stáhnout Analýzu (.xlsx)", buffer.getvalue(), "Logistics_Analysis_v2.3.xlsx")

    except Exception as e:
        st.error(f"Chyba: {e}")
