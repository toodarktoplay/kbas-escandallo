"""
Escandallo — Kbas Office
Sube el Excel del contenedor (referencias, cantidades y precio USD), pon los
gastos y descubre el coste real puesto en Gata y el margen que deja la regla ×2,5.
"""
import pandas as pd
import streamlit as st

from escandallo_core import (
    calcular,
    detectar_columnas,
    excel_resultado,
    plantilla_excel,
    preparar_datos,
)

st.set_page_config(page_title="Escandallo · Kbas Office", page_icon="💰", layout="wide")

# Paleta Kbas (ajústala a los hex oficiales del portal si difieren)
CHOCOLATE = "#4A2C1D"
SAND = "#E8D5BE"
MALVA = "#A98BA3"
DUSTY = "#7F9CC1"
TINTA = "#1F1B1A"

st.markdown(
    f"""
    <style>
      .stApp {{ background: #FBF7F2; }}
      h1, h2, h3 {{ color: {CHOCOLATE}; }}
      div[data-testid="stMetric"] {{
          background: white; border-radius: 14px; padding: 14px 16px;
          border-top: 4px solid {MALVA}; box-shadow: 0 1px 4px rgba(0,0,0,.06);
      }}
      .kbas-nota {{ background: {SAND}; border-radius: 12px; padding: 14px 18px; color: {TINTA}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("💰 Escandallo")
st.caption("Coste real de cada referencia puesta en Gata, y el margen que de verdad deja el ×2,5.")

# ---------------------------------------------------------------------------
# 1. Excel
# ---------------------------------------------------------------------------
col_a, col_b = st.columns([3, 1])
with col_a:
    archivo = st.file_uploader(
        "Excel del contenedor (invoice del proveedor o exportación del ERP)",
        type=["xlsx", "xls", "csv"],
        help="Columnas mínimas: Referencia, Cantidad y Precio USD. Opcionales: Descripción, CBM y Arancel %.",
    )
with col_b:
    st.write("")
    st.download_button(
        "📄 Descargar plantilla",
        plantilla_excel(),
        file_name="plantilla_escandallo.xlsx",
        use_container_width=True,
    )

if not archivo:
    st.markdown(
        '<div class="kbas-nota">Sube el Excel con las referencias del contenedor. '
        "Si no tienes uno a mano, descarga la plantilla y prueba con los datos de ejemplo.</div>",
        unsafe_allow_html=True,
    )
    st.stop()

df_raw = pd.read_csv(archivo) if archivo.name.lower().endswith(".csv") else pd.read_excel(archivo)
mapeo = detectar_columnas(df_raw)

with st.expander("Columnas del Excel", expanded=not all(k in mapeo for k in ("referencia", "cantidad", "precio_usd"))):
    opciones = ["—"] + list(df_raw.columns)

    def selector(campo, etiqueta, obligatorio=False):
        actual = mapeo.get(campo)
        idx = opciones.index(actual) if actual in opciones else 0
        elegido = st.selectbox(etiqueta + (" *" if obligatorio else ""), opciones, index=idx, key=f"col_{campo}")
        if elegido != "—":
            mapeo[campo] = elegido
        else:
            mapeo.pop(campo, None)

    c1, c2, c3 = st.columns(3)
    with c1:
        selector("referencia", "Referencia", True)
        selector("descripcion", "Descripción")
    with c2:
        selector("cantidad", "Cantidad", True)
        selector("precio_usd", "Precio USD", True)
    with c3:
        selector("cbm", "CBM (volumen de la línea)")
        selector("arancel", "Arancel % por referencia")

if not all(k in mapeo for k in ("referencia", "cantidad", "precio_usd")):
    st.warning("Indica qué columnas son Referencia, Cantidad y Precio USD.")
    st.stop()

datos = preparar_datos(df_raw, mapeo)
if datos.empty:
    st.error("No he encontrado filas con cantidad y precio válidos.")
    st.stop()

# ---------------------------------------------------------------------------
# 2. Gastos del contenedor
# ---------------------------------------------------------------------------
st.subheader("Gastos del contenedor")
g1, g2, g3, g4 = st.columns(4)
with g1:
    eur_usd = st.number_input("Cambio: 1 € = X USD", min_value=0.5, max_value=2.0, value=1.08, step=0.01, format="%.3f")
    flete = st.number_input("Flete marítimo (€)", min_value=0.0, value=2500.0, step=100.0)
with g2:
    aduana = st.number_input("Aduana / despacho (€)", min_value=0.0, value=450.0, step=50.0)
    transporte = st.number_input("Transporte puerto → Gata (€)", min_value=0.0, value=600.0, step=50.0)
with g3:
    otros = st.number_input("Otros (seguro, inspección…) (€)", min_value=0.0, value=0.0, step=50.0)
    arancel = st.number_input(
        "Arancel por defecto (%)", min_value=0.0, max_value=30.0, value=3.7, step=0.1,
        help="Se usa en las referencias que no traigan su propio arancel en el Excel. Consulta el TARIC de cada familia.",
    )
with g4:
    opciones_reparto = {"Por valor de compra": "valor", "Por unidades": "unidades"}
    if "cbm" in mapeo:
        opciones_reparto["Por volumen (CBM)"] = "volumen"
    reparto_txt = st.radio("Reparto de gastos", list(opciones_reparto), index=0)
    coef = st.number_input("Regla de precio: USD ×", min_value=1.0, max_value=5.0, value=2.5, step=0.1)

with st.expander("Semáforo"):
    s1, s2 = st.columns(2)
    verde = s1.number_input("🟢 Multiplicador real a partir de", value=2.2, step=0.1)
    amarillo = s2.number_input("🟡 Multiplicador real a partir de (por debajo, 🔴)", value=1.9, step=0.1)

d, r = calcular(
    datos, eur_usd, flete, aduana, transporte, otros, arancel,
    opciones_reparto[reparto_txt], coef, verde, amarillo,
)

# ---------------------------------------------------------------------------
# 3. Resultado
# ---------------------------------------------------------------------------
st.subheader("Resultado")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Coste real total", f"{r['coste_total']:,.0f} €".replace(",", "."))
m2.metric("Gastos sobre la compra", f"{r['gastos_sobre_fob_pct']:.1f} %")
m3.metric("Venta potencial", f"{r['ventas']:,.0f} €".replace(",", "."))
m4.metric("Margen bruto", f"{r['margen_pct']:.1f} %")
m5.metric("Multiplicador real", f"×{r['mult_medio']:.2f}")

st.markdown(
    f'<div class="kbas-nota">Con el cambio a <b>{eur_usd:.3f}</b> y estos gastos, la regla '
    f"<b>USD × {coef:g}</b> equivale a multiplicar el coste real por <b>×{r['mult_medio']:.2f}</b>. "
    f"Semáforo: 🟢 {r['verdes']} · 🟡 {r['amarillos']} · 🔴 {r['rojos']} referencias.</div>",
    unsafe_allow_html=True,
)
st.write("")

vista = d.sort_values("mult_real")[[
    "semaforo", "referencia", "descripcion", "cantidad", "precio_usd", "coste_ud",
    "pv_ud", "margen_ud", "margen_pct", "mult_real", "pv_para_verde",
]].rename(columns={
    "semaforo": "", "referencia": "Referencia", "descripcion": "Descripción", "cantidad": "Uds",
    "precio_usd": "Precio USD", "coste_ud": "Coste real €", "pv_ud": "PV actual €",
    "margen_ud": "Margen €", "margen_pct": "Margen %", "mult_real": "Mult. real",
    "pv_para_verde": "PV mínimo 🟢",
})
if not mapeo.get("descripcion"):
    vista = vista.drop(columns=["Descripción"])

st.dataframe(
    vista,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Precio USD": st.column_config.NumberColumn(format="%.2f $"),
        "Coste real €": st.column_config.NumberColumn(format="%.2f €"),
        "PV actual €": st.column_config.NumberColumn(format="%.2f €"),
        "Margen €": st.column_config.NumberColumn(format="%.2f €"),
        "Margen %": st.column_config.NumberColumn(format="%.1f %%"),
        "Mult. real": st.column_config.NumberColumn(format="×%.2f"),
        "PV mínimo 🟢": st.column_config.NumberColumn(format="%.2f €"),
    },
)

params = dict(eur_usd=eur_usd, flete=flete, aduana=aduana, transporte=transporte,
              otros=otros, arancel=arancel, reparto=reparto_txt, coef=coef)
nombre = archivo.name.rsplit(".", 1)[0]
st.download_button(
    "⬇️ Descargar escandallo en Excel",
    excel_resultado(d, r, params),
    file_name=f"escandallo_{nombre}.xlsx",
    type="primary",
)
