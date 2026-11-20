"""
Escandallo Kbas — lógica de cálculo (sin Streamlit, para poder probarla aparte).

Regla actual de Kbas: precio proveedor en USD × 2,5 = precio de venta en €.
Esta herramienta calcula el coste REAL puesto en almacén (cambio, flete,
aduana, aranceles, transporte) y enseña qué multiplicador y margen reales
quedan detrás de ese ×2,5.
"""
from __future__ import annotations

import io
import unicodedata

import pandas as pd

# ---------------------------------------------------------------------------
# Lectura flexible del Excel
# ---------------------------------------------------------------------------

ALIAS = {
    "referencia": ["referencia", "ref", "ref.", "codigo", "código", "articulo", "artículo", "item", "style", "model"],
    "descripcion": ["descripcion", "descripción", "desc", "description", "nombre"],
    "cantidad": ["cantidad", "cant", "uds", "unidades", "qty", "quantity", "pcs"],
    "precio_usd": ["precio usd", "precio_usd", "usd", "precio", "price", "unit price", "fob", "precio fob"],
    "cbm": ["cbm", "m3", "volumen", "volume"],
    "arancel": ["arancel", "arancel %", "duty", "duty %", "taric %"],
}


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return txt.strip().lower()


def detectar_columnas(df: pd.DataFrame) -> dict:
    """Devuelve {campo: nombre_columna_original} para las columnas reconocidas."""
    encontrados = {}
    normas = {_norm(c): c for c in df.columns}
    for campo, alias in ALIAS.items():
        for a in alias:
            if _norm(a) in normas:
                encontrados[campo] = normas[_norm(a)]
                break
    return encontrados


def preparar_datos(df: pd.DataFrame, mapeo: dict) -> pd.DataFrame:
    out = pd.DataFrame()
    out["referencia"] = df[mapeo["referencia"]].astype(str).str.strip()
    out["descripcion"] = df[mapeo["descripcion"]].astype(str) if mapeo.get("descripcion") else ""
    out["cantidad"] = pd.to_numeric(df[mapeo["cantidad"]], errors="coerce")
    out["precio_usd"] = pd.to_numeric(
        df[mapeo["precio_usd"]].astype(str).str.replace(",", ".", regex=False).str.replace("$", "", regex=False),
        errors="coerce",
    )
    out["cbm"] = pd.to_numeric(df[mapeo["cbm"]], errors="coerce") if mapeo.get("cbm") else pd.NA
    out["arancel"] = pd.to_numeric(df[mapeo["arancel"]], errors="coerce") if mapeo.get("arancel") else pd.NA
    out = out.dropna(subset=["cantidad", "precio_usd"])
    out = out[(out["cantidad"] > 0) & (out["referencia"] != "") & (out["referencia"].str.lower() != "nan")]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

def calcular(
    datos: pd.DataFrame,
    eur_usd: float,          # 1 € = X USD (ej. 1,08)
    flete: float,            # € flete marítimo del contenedor
    aduana: float,           # € despacho / agente de aduanas
    transporte: float,       # € transporte puerto → Gata
    otros: float,            # € otros gastos (seguro, inspección…)
    arancel_defecto: float,  # % arancel si la fila no trae el suyo
    reparto: str,            # "valor" | "unidades" | "volumen"
    coef: float = 2.5,       # regla Kbas: USD × coef = € venta
    umbral_verde: float = 2.2,
    umbral_amarillo: float = 1.9,
) -> tuple[pd.DataFrame, dict]:
    d = datos.copy()
    d["fob_eur_ud"] = d["precio_usd"] / eur_usd
    d["valor_eur"] = d["fob_eur_ud"] * d["cantidad"]

    if reparto == "volumen" and d["cbm"].notna().any():
        peso = d["cbm"].fillna(0).astype(float)
    elif reparto == "unidades":
        peso = d["cantidad"].astype(float)
    else:
        peso = d["valor_eur"].astype(float)
    total_peso = peso.sum() or 1.0
    cuota = peso / total_peso

    d["flete_eur"] = cuota * flete
    d["otros_gastos_eur"] = cuota * (aduana + transporte + otros)
    arancel_pct = d["arancel"].astype("Float64").fillna(arancel_defecto).astype(float)
    # Base del arancel ≈ valor en aduana (CIF): producto + flete
    d["arancel_eur"] = (d["valor_eur"] + d["flete_eur"]) * arancel_pct / 100
    d["arancel_pct"] = arancel_pct

    d["coste_total_eur"] = d["valor_eur"] + d["flete_eur"] + d["otros_gastos_eur"] + d["arancel_eur"]
    d["coste_ud"] = d["coste_total_eur"] / d["cantidad"]
    d["gastos_sobre_fob_pct"] = (d["coste_ud"] / d["fob_eur_ud"] - 1) * 100

    d["pv_ud"] = d["precio_usd"] * coef                    # regla actual
    d["margen_ud"] = d["pv_ud"] - d["coste_ud"]
    d["margen_pct"] = d["margen_ud"] / d["pv_ud"] * 100
    d["mult_real"] = d["pv_ud"] / d["coste_ud"]
    d["pv_para_verde"] = d["coste_ud"] * umbral_verde       # precio mínimo para quedar en verde

    def semaforo(m):
        if m >= umbral_verde:
            return "🟢"
        if m >= umbral_amarillo:
            return "🟡"
        return "🔴"

    d["semaforo"] = d["mult_real"].apply(semaforo)

    ventas = (d["pv_ud"] * d["cantidad"]).sum()
    coste = d["coste_total_eur"].sum()
    resumen = {
        "referencias": len(d),
        "unidades": int(d["cantidad"].sum()),
        "fob_eur": d["valor_eur"].sum(),
        "flete": d["flete_eur"].sum(),
        "otros_gastos": d["otros_gastos_eur"].sum(),
        "aranceles": d["arancel_eur"].sum(),
        "coste_total": coste,
        "ventas": ventas,
        "margen": ventas - coste,
        "margen_pct": (ventas - coste) / ventas * 100 if ventas else 0,
        "mult_medio": ventas / coste if coste else 0,
        "gastos_sobre_fob_pct": (coste / d["valor_eur"].sum() - 1) * 100 if len(d) else 0,
        "rojos": int((d["semaforo"] == "🔴").sum()),
        "amarillos": int((d["semaforo"] == "🟡").sum()),
        "verdes": int((d["semaforo"] == "🟢").sum()),
    }
    return d, resumen


# ---------------------------------------------------------------------------
# Excel de salida
# ---------------------------------------------------------------------------

COLUMNAS_SALIDA = [
    ("semaforo", "", 4),
    ("referencia", "Referencia", 14),
    ("descripcion", "Descripción", 28),
    ("cantidad", "Uds", 7),
    ("precio_usd", "Precio USD", 11),
    ("fob_eur_ud", "Precio en €", 11),
    ("coste_ud", "Coste real €/ud", 13),
    ("gastos_sobre_fob_pct", "Gastos s/ compra %", 12),
    ("pv_ud", "PV actual € (×coef)", 14),
    ("margen_ud", "Margen €/ud", 11),
    ("margen_pct", "Margen %", 10),
    ("mult_real", "Multiplicador real", 12),
    ("pv_para_verde", "PV mínimo para 🟢", 13),
    ("arancel_pct", "Arancel %", 9),
]


def excel_resultado(d: pd.DataFrame, resumen: dict, params: dict) -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    tabla = d[[c for c, _, _ in COLUMNAS_SALIDA]].copy()
    tabla.columns = [t for _, t, _ in COLUMNAS_SALIDA]
    tabla = tabla.sort_values("Multiplicador real")

    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, sheet_name="Escandallo", index=False)
        ws = xw.sheets["Escandallo"]
        cab = PatternFill("solid", fgColor="4A2C1D")
        for i, (_, _, ancho) in enumerate(COLUMNAS_SALIDA, start=1):
            col = get_column_letter(i)
            ws.column_dimensions[col].width = ancho
            c = ws[f"{col}1"]
            c.fill = cab
            c.font = Font(bold=True, color="FFFFFF")
            c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.row_dimensions[1].height = 32
        ws.freeze_panes = "B2"

        formatos = {
            "Precio USD": '#,##0.00 "$"', "Precio en €": '#,##0.00 "€"', "Coste real €/ud": '#,##0.00 "€"',
            "PV actual € (×coef)": '#,##0.00 "€"', "Margen €/ud": '#,##0.00 "€"', "PV mínimo para 🟢": '#,##0.00 "€"',
            "Gastos s/ compra %": '0.0"%"', "Margen %": '0.0"%"', "Multiplicador real": '0.00"×"', "Arancel %": '0.0"%"',
        }
        colores = {"🟢": "D8EBD3", "🟡": "FBEFC5", "🔴": "F6D3D0"}
        titulos = list(tabla.columns)
        for fila in range(2, len(tabla) + 2):
            sem = ws.cell(row=fila, column=1).value
            relleno = PatternFill("solid", fgColor=colores.get(sem, "FFFFFF"))
            for j, titulo in enumerate(titulos, start=1):
                celda = ws.cell(row=fila, column=j)
                if titulo in formatos:
                    celda.number_format = formatos[titulo]
                if titulo in ("Multiplicador real", "Margen %"):
                    celda.fill = relleno
                    celda.font = Font(bold=True)

        # Hoja resumen
        filas = [
            ("Parámetros", ""),
            ("Cambio (1 € = X USD)", params["eur_usd"]),
            ("Flete contenedor €", params["flete"]),
            ("Aduana / despacho €", params["aduana"]),
            ("Transporte a Gata €", params["transporte"]),
            ("Otros gastos €", params["otros"]),
            ("Arancel por defecto %", params["arancel"]),
            ("Reparto de gastos", params["reparto"]),
            ("Regla de precio", f"USD × {params['coef']} = €"),
            ("", ""),
            ("Resultado del contenedor", ""),
            ("Referencias", resumen["referencias"]),
            ("Unidades", resumen["unidades"]),
            ("Compra en € (sin gastos)", round(resumen["fob_eur"], 2)),
            ("Flete", round(resumen["flete"], 2)),
            ("Aduana + transporte + otros", round(resumen["otros_gastos"], 2)),
            ("Aranceles", round(resumen["aranceles"], 2)),
            ("Coste real total", round(resumen["coste_total"], 2)),
            ("Gastos sobre la compra %", round(resumen["gastos_sobre_fob_pct"], 1)),
            ("Venta potencial (regla actual)", round(resumen["ventas"], 2)),
            ("Margen bruto €", round(resumen["margen"], 2)),
            ("Margen bruto %", round(resumen["margen_pct"], 1)),
            ("Multiplicador real medio", round(resumen["mult_medio"], 2)),
            ("🟢 / 🟡 / 🔴", f"{resumen['verdes']} / {resumen['amarillos']} / {resumen['rojos']}"),
        ]
        pd.DataFrame(filas, columns=["Concepto", "Valor"]).to_excel(xw, sheet_name="Resumen", index=False)
        wr = xw.sheets["Resumen"]
        wr.column_dimensions["A"].width = 34
        wr.column_dimensions["B"].width = 18
        for celda in ("A1", "B1"):
            wr[celda].fill = cab
            wr[celda].font = Font(bold=True, color="FFFFFF")
        for fila in (2, 12):
            wr.cell(row=fila, column=1).font = Font(bold=True, color="4A2C1D")
    return buf.getvalue()


def plantilla_excel() -> bytes:
    ejemplo = pd.DataFrame({
        "Referencia": ["KB366", "KB412", "VB201"],
        "Descripción": ["Bolso rafia natural", "Sombrero paja ala ancha", "Bolso piel tote"],
        "Cantidad": [300, 500, 120],
        "Precio USD": [8.20, 3.40, 22.50],
        "CBM": [1.8, 4.5, 0.9],
        "Arancel %": [3.7, 3.7, 3.0],
    })
    buf = io.BytesIO()
    ejemplo.to_excel(buf, index=False)
    return buf.getvalue()
