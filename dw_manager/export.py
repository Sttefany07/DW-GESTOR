from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd


def dataframe_to_excel_bytes(
    resumen: pd.DataFrame,
    detalle: pd.DataFrame,
    datos_filtrados: pd.DataFrame,
    filtros: dict[str, Any],
    alertas_tarifa: pd.DataFrame | None = None,
) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        resumen.to_excel(writer, index=False, sheet_name="Resumen")
        detalle.to_excel(writer, index=False, sheet_name="Detalle")
        datos_filtrados.to_excel(writer, index=False, sheet_name="Datos filtrados")
        filtros_df = pd.DataFrame([{"filtro": k, "valor": v} for k, v in filtros.items()])
        filtros_df.to_excel(writer, index=False, sheet_name="Filtros")
        if alertas_tarifa is not None and not alertas_tarifa.empty:
            alertas_tarifa.to_excel(writer, index=False, sheet_name="Alertas tarifas")

        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "#FFFFFF", "border": 1})
        money_fmt = workbook.add_format({"num_format": "$#,##0.00"})
        hours_fmt = workbook.add_format({"num_format": "#,##0.00"})
        text_fmt = workbook.add_format({"text_wrap": False})

        for sheet_name, df in {
            "Resumen": resumen,
            "Detalle": detalle,
            "Datos filtrados": datos_filtrados,
            "Filtros": filtros_df,
            "Alertas tarifas": alertas_tarifa if alertas_tarifa is not None else pd.DataFrame(),
        }.items():
            if sheet_name not in writer.sheets:
                continue
            ws = writer.sheets[sheet_name]
            ws.freeze_panes(1, 0)
            for col_idx, col_name in enumerate(df.columns if df is not None else []):
                ws.write(0, col_idx, col_name, header_fmt)
                width = min(max(len(str(col_name)) + 2, 14), 35)
                ws.set_column(col_idx, col_idx, width, text_fmt)
                if "hora" in str(col_name).lower() or "duracion" in str(col_name).lower():
                    ws.set_column(col_idx, col_idx, width, hours_fmt)
                if any(x in str(col_name).lower() for x in ["facturacion", "facturación", "costo", "margen", "resultado operativo", "tarifa"]):
                    ws.set_column(col_idx, col_idx, width, money_fmt)
            if df is not None and not df.empty:
                ws.autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))
    output.seek(0)
    return output.getvalue()
