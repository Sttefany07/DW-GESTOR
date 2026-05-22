from __future__ import annotations

from datetime import date
from typing import Any
import re
import unicodedata

import pandas as pd


# -----------------------------------------------------------------------------
# Normalización y fechas
# -----------------------------------------------------------------------------

def _norm(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def _date_in_range(ref: Any, start: Any, end: Any) -> bool:
    if ref is None or pd.isna(ref):
        ref_date = pd.Timestamp.today().normalize()
    else:
        ref_date = pd.to_datetime(ref, errors="coerce")
        if pd.isna(ref_date):
            ref_date = pd.Timestamp.today().normalize()
    start_date = pd.to_datetime(start, errors="coerce")
    end_date = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_date) or pd.isna(end_date):
        return False
    return start_date <= ref_date <= end_date


def _first_non_empty(row: pd.Series, columns: list[str]) -> str:
    for col in columns:
        if col in row.index:
            value = row.get(col)
            if value is not None and not pd.isna(value) and str(value).strip():
                return str(value).strip()
    return ""


# -----------------------------------------------------------------------------
# Tarifas
# -----------------------------------------------------------------------------

def _select_tariff(
    record: pd.Series,
    tarifas: pd.DataFrame,
    record_value: Any,
    tariff_key_col: str,
    value_col: str,
    id_col: str,
    empty_message: str,
) -> tuple[float, str]:
    """Selecciona tarifa por clave y vigencia.

    La lógica siempre es directa: horas x tarifa. No se divide tarifa.
    Si no encuentra una tarifa dentro de vigencia, usa la más reciente de la misma clave
    para evitar que el cálculo quede en cero cuando la tarifa ya fue registrada.
    """
    if tarifas is None or tarifas.empty:
        return 0.0, "Sin tarifas cargadas"

    key_value = _norm(record_value)
    if not key_value:
        return 0.0, empty_message

    if tariff_key_col not in tarifas.columns:
        return 0.0, f"Falta columna de tarifa: {tariff_key_col}"

    candidates: list[tuple[int, str, int, pd.Series]] = []
    for _, tarifa in tarifas.iterrows():
        if _norm(tarifa.get(tariff_key_col)) != key_value:
            continue

        in_range = _date_in_range(
            record.get("fecha_referencia"),
            tarifa.get("fecha_inicio_vigencia"),
            tarifa.get("fecha_fin_vigencia"),
        )
        vigente = 1 if str(tarifa.get("estado", "")).upper() == "VIGENTE" else 0
        start = str(tarifa.get("fecha_inicio_vigencia") or "")
        try:
            tariff_id = int(tarifa.get(id_col) or 0)
        except Exception:
            tariff_id = 0

        score = (10 if in_range else 0) + (2 if vigente else 0)
        candidates.append((score, start, tariff_id, tarifa))

    if not candidates:
        return 0.0, f"Sin tarifa para: {record_value}"

    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    selected = candidates[0][3]
    return float(selected.get(value_col) or 0), f"{id_col}:{selected.get(id_col)}"


def _select_tariff_multi(
    record: pd.Series,
    tarifas: pd.DataFrame,
    match_pairs: list[tuple[Any, str]],
    value_col: str,
    id_col: str,
    empty_message: str,
) -> tuple[float, str]:
    """Selecciona tarifa por varias claves y vigencia.

    Se usa para tarifa comercial por proyecto + rol asignado.
    Si no encuentra una tarifa dentro de vigencia, toma la más reciente de la
    misma combinación para evitar ceros cuando la vigencia del Excel difiere.
    """
    if tarifas is None or tarifas.empty:
        return 0.0, "Sin tarifas cargadas"

    for record_value, tariff_col in match_pairs:
        if not _norm(record_value):
            return 0.0, empty_message
        if tariff_col not in tarifas.columns:
            return 0.0, f"Falta columna de tarifa: {tariff_col}"

    candidates: list[tuple[int, str, int, pd.Series]] = []
    for _, tarifa in tarifas.iterrows():
        ok = True
        for record_value, tariff_col in match_pairs:
            if _norm(tarifa.get(tariff_col)) != _norm(record_value):
                ok = False
                break
        if not ok:
            continue

        in_range = _date_in_range(
            record.get("fecha_referencia"),
            tarifa.get("fecha_inicio_vigencia"),
            tarifa.get("fecha_fin_vigencia"),
        )
        vigente = 1 if str(tarifa.get("estado", "")).upper() == "VIGENTE" else 0
        start = str(tarifa.get("fecha_inicio_vigencia") or "")
        try:
            tariff_id = int(tarifa.get(id_col) or 0)
        except Exception:
            tariff_id = 0

        score = (10 if in_range else 0) + (2 if vigente else 0)
        candidates.append((score, start, tariff_id, tarifa))

    if not candidates:
        keys = " · ".join(str(v) for v, _ in match_pairs)
        return 0.0, f"Sin tarifa para: {keys}"

    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    selected = candidates[0][3]
    return float(selected.get(value_col) or 0), f"{id_col}:{selected.get(id_col)}"


def apply_tariffs(
    df: pd.DataFrame,
    tarifas_dw: pd.DataFrame,
    tarifas_comerciales: pd.DataFrame,
    commercial_basis: str = "proyecto_rol",
) -> pd.DataFrame:
    """Aplica tarifas a los registros ClickUp.

    Regla v19 del mini sistema:
    - Tarifa de operaciones = siempre por rol interno/rol estimado.
    - Tarifa comercial = por proyecto + rol asignado/comercial.
    - No se necesita asignación manual de consultores a proyecto.

    Fórmulas Gerencia General:
    Facturación estimada comercial = Horas estimadas × Tarifa comercial del proyecto y rol asignado
    Facturación registrada comercial = Horas registradas × Tarifa comercial del proyecto y rol asignado
    Costo real comercial = Horas facturables × Tarifa comercial del proyecto y rol asignado
    Costo real operaciones = Horas facturables × Tarifa operaciones del rol interno
    Resultado operativo = Costo real comercial - Costo real operaciones
    Progreso = Horas registradas / Horas estimadas

    Fórmulas Gerencia de Servicios:
    Facturación estimada operaciones = Horas estimadas × Tarifa operaciones del rol interno
    Facturación registrada operaciones = Horas registradas × Tarifa operaciones del rol interno
    Costo real operaciones = Horas facturables × Tarifa operaciones del rol interno
    """
    out = df.copy()
    if out.empty:
        return out

    # Rol estimado: viene de ClickUp como rol interno.
    out["rol_estimado"] = out.get("rol", "").fillna("").astype(str)

    # Rol asignado: para cálculo comercial se usa el rol comercial de ClickUp.
    # Si ClickUp no lo trae, se usa como respaldo el rol estimado.
    out["rol_asignado"] = out.apply(
        lambda r: _first_non_empty(r, ["rol_facturable", "rol_facturable_estimado", "rol", "rol_estimado"]),
        axis=1,
    )
    out["rol_comercial_asignado"] = out["rol_asignado"]

    out["rol_tarifa_operaciones"] = out["rol_estimado"]
    out["rol_tarifa_comercial"] = out["rol_asignado"]
    out["proyecto_tarifa_comercial"] = out.get("proyecto", "")
    out["base_tarifa_comercial"] = "Proyecto + rol asignado"

    dw_values = out.apply(
        lambda row: _select_tariff(
            row,
            tarifas_dw,
            row.get("rol_tarifa_operaciones"),
            "rol_interno",
            "tarifa_real_dw_hora",
            "id_tarifa_dw",
            "Sin rol interno para tarifa operaciones",
        ),
        axis=1,
    )

    com_values = out.apply(
        lambda row: _select_tariff_multi(
            row,
            tarifas_comerciales,
            [(row.get("proyecto_tarifa_comercial"), "proyecto"), (row.get("rol_tarifa_comercial"), "rol_facturable")],
            "tarifa_comercial_hora",
            "id_tarifa_comercial",
            "Sin proyecto o rol asignado para tarifa comercial",
        ),
        axis=1,
    )

    out["tarifa_operaciones_hora"] = [v[0] for v in dw_values]
    out["tarifa_real_dw_hora"] = out["tarifa_operaciones_hora"]
    out["tarifa_dw_fuente"] = [v[1] for v in dw_values]
    out["tarifa_comercial_hora"] = [v[0] for v in com_values]
    out["tarifa_facturable_hora"] = out["tarifa_comercial_hora"]
    out["tarifa_comercial_fuente"] = [v[1] for v in com_values]

    for col in ["horas_estimadas", "horas_registradas", "horas_facturables", "tarifa_real_dw_hora", "tarifa_facturable_hora"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    # Gerencia General: montos comerciales por proyecto + rol asignado.
    out["facturacion_estimada"] = out["horas_estimadas"] * out["tarifa_facturable_hora"]
    out["facturacion_registrada"] = out["horas_registradas"] * out["tarifa_facturable_hora"]
    out["facturacion_real"] = out["horas_facturables"] * out["tarifa_facturable_hora"]
    out["costo_real_comercial"] = out["facturacion_real"]

    # Gerencia de Servicios / Operaciones: montos operativos por tarifa de operaciones.
    out["facturacion_estimada_operaciones"] = out["horas_estimadas"] * out["tarifa_real_dw_hora"]
    out["facturacion_registrada_operaciones"] = out["horas_registradas"] * out["tarifa_real_dw_hora"]
    out["costo_dw_real"] = out["horas_facturables"] * out["tarifa_real_dw_hora"]
    out["costo_real_operaciones"] = out["costo_dw_real"]

    out["margen_real"] = out["costo_real_comercial"] - out["costo_real_operaciones"]
    out["resultado_operativo"] = out["margen_real"]
    out["margen_pct"] = out.apply(lambda r: (r["resultado_operativo"] / r["costo_real_comercial"]) if r["costo_real_comercial"] else 0, axis=1)
    out["progreso"] = out.apply(lambda r: (r["horas_registradas"] / r["horas_estimadas"]) if r["horas_estimadas"] else 0, axis=1)

    out["alerta_tarifa"] = ""
    out.loc[out["tarifa_real_dw_hora"].eq(0), "alerta_tarifa"] += "Sin tarifa operaciones por rol interno; "
    out.loc[out["tarifa_facturable_hora"].eq(0), "alerta_tarifa"] += "Sin tarifa comercial por proyecto y rol asignado; "
    return out


# -----------------------------------------------------------------------------
# Asignaciones, filtros y métricas
# -----------------------------------------------------------------------------

def apply_project_assignments(df: pd.DataFrame, asignaciones: pd.DataFrame) -> pd.DataFrame:
    """Conecta horas ClickUp con asignaciones operativas.

    - Rol estimado = rol que llega desde ClickUp.
    - Rol asignado = rol de la asignación; si no existe asignación, se usa el rol estimado.
    """
    out = df.copy()
    if out.empty:
        return out

    out["rol_estimado"] = out.get("rol", "")
    out["rol_facturable_estimado"] = out.get("rol_facturable", "")
    out["asignacion_estado"] = "Sin asignación"
    out["rol_interno_asignado"] = ""
    out["rol_facturable_asignado"] = ""

    if asignaciones is None or asignaciones.empty:
        out["rol_asignado"] = out["rol_estimado"]
        out["rol_comercial_asignado"] = out["rol_facturable_estimado"]
        return out

    asign = asignaciones.copy()
    rename_map = {
        "Consultor": "consultor", "País": "pais", "Cliente": "cliente", "Proyecto": "proyecto",
        "Hito facturable": "hito_facturable", "Rol interno": "rol_interno",
        "Rol facturable": "rol_facturable", "Fecha inicio": "fecha_inicio", "Fecha fin": "fecha_fin",
        "Estado": "estado",
    }
    asign = asign.rename(columns={k: v for k, v in rename_map.items() if k in asign.columns})
    needed = {"consultor", "pais", "cliente", "proyecto", "hito_facturable", "fecha_inicio", "fecha_fin"}
    if not needed.issubset(set(asign.columns)):
        out["rol_asignado"] = out["rol_estimado"]
        out["rol_comercial_asignado"] = out["rol_facturable_estimado"]
        return out

    def find_assignment(row: pd.Series) -> tuple[str, str, str]:
        persona = _norm(row.get("assignee"))
        pais = _norm(row.get("pais"))
        cliente = _norm(row.get("cliente"))
        proyecto = _norm(row.get("proyecto"))
        hito = _norm(row.get("hito_facturable"))
        ref = row.get("fecha_referencia")
        if not persona or not proyecto:
            return "Sin asignación", "", ""

        candidates = asign[
            (asign["consultor"].map(_norm) == persona)
            & (asign["pais"].map(_norm) == pais)
            & (asign["cliente"].map(_norm) == cliente)
            & (asign["proyecto"].map(_norm) == proyecto)
        ].copy()
        if "estado" in candidates.columns:
            candidates = candidates[candidates["estado"].astype(str).str.upper().isin(["ACTIVA", "1", "TRUE", "VIGENTE"])]
        if candidates.empty:
            return "Sin asignación", "", ""

        scored = []
        for _, a in candidates.iterrows():
            ahito = _norm(a.get("hito_facturable"))
            todo = ahito in {"", "todo el proyecto", "no aplica"}
            match_hito = todo or ahito == hito
            if not match_hito:
                continue
            if not _date_in_range(ref, a.get("fecha_inicio"), a.get("fecha_fin")):
                continue
            score = 2 if not todo else 1
            scored.append((score, a))
        if not scored:
            return "Sin asignación", "", ""
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = scored[0][1]
        return "Asignado", str(selected.get("rol_interno") or ""), str(selected.get("rol_facturable") or "")

    vals = out.apply(find_assignment, axis=1)
    out["asignacion_estado"] = [v[0] for v in vals]
    out["rol_interno_asignado"] = [v[1] for v in vals]
    out["rol_facturable_asignado"] = [v[2] for v in vals]
    out["rol_asignado"] = out.apply(lambda r: _first_non_empty(r, ["rol_interno_asignado", "rol_estimado", "rol"]), axis=1)
    out["rol_comercial_asignado"] = out.apply(lambda r: _first_non_empty(r, ["rol_facturable_asignado", "rol_facturable_estimado", "rol_facturable", "rol_asignado"]), axis=1)

    # Para compatibilidad con vistas previas antiguas, llenar solo si ClickUp vino vacío.
    mask_rol = out.get("rol", pd.Series(index=out.index, dtype=object)).fillna("").astype(str).str.strip().eq("")
    out.loc[mask_rol, "rol"] = out.loc[mask_rol, "rol_asignado"]
    mask_rol_fac = out.get("rol_facturable", pd.Series(index=out.index, dtype=object)).fillna("").astype(str).str.strip().eq("")
    out.loc[mask_rol_fac, "rol_facturable"] = out.loc[mask_rol_fac, "rol_comercial_asignado"]
    return out


def total_metrics(df: pd.DataFrame) -> dict[str, float]:
    keys = [
        "total_estimado", "total_registrado", "facturable_real_horas",
        "facturacion_estimada", "facturacion_registrada", "facturacion_real",
        "costo_real_comercial", "costo_dw_real", "costo_real_operaciones",
        "facturacion_estimada_operaciones", "facturacion_registrada_operaciones",
        "margen_real", "resultado_operativo", "margen_pct", "progreso",
    ]
    if df.empty:
        return {k: 0.0 for k in keys}
    costo_comercial = float(df.get("costo_real_comercial", df.get("facturacion_real", 0)).sum())
    resultado = float(df.get("margen_real", 0).sum())
    horas_estimadas = float(df["horas_estimadas"].sum())
    horas_registradas = float(df["horas_registradas"].sum())
    return {
        "total_estimado": horas_estimadas,
        "total_registrado": horas_registradas,
        "facturable_real_horas": float(df["horas_facturables"].sum()),
        "facturacion_estimada": float(df["facturacion_estimada"].sum()),
        "facturacion_registrada": float(df["facturacion_registrada"].sum()),
        "facturacion_real": float(df["facturacion_real"].sum()),
        "facturacion_estimada_operaciones": float(df.get("facturacion_estimada_operaciones", 0).sum()),
        "facturacion_registrada_operaciones": float(df.get("facturacion_registrada_operaciones", 0).sum()),
        "costo_real_comercial": costo_comercial,
        "costo_dw_real": float(df["costo_dw_real"].sum()),
        "costo_real_operaciones": float(df.get("costo_real_operaciones", df.get("costo_dw_real", 0)).sum()),
        "margen_real": resultado,
        "resultado_operativo": resultado,
        "margen_pct": resultado / costo_comercial if costo_comercial else 0.0,
        "progreso": horas_registradas / horas_estimadas if horas_estimadas else 0.0,
    }


def _weighted_rate(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def build_summary(df: pd.DataFrame, mode: str = "general") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    group_cols = ["pais", "proyecto"]
    agg = df.groupby(group_cols, dropna=False).agg(
        horas_estimadas=("horas_estimadas", "sum"),
        horas_registradas=("horas_registradas", "sum"),
        horas_facturables=("horas_facturables", "sum"),
        facturacion_estimada=("facturacion_estimada", "sum"),
        facturacion_registrada=("facturacion_registrada", "sum"),
        facturacion_real=("facturacion_real", "sum"),
        facturacion_estimada_operaciones=("facturacion_estimada_operaciones", "sum"),
        facturacion_registrada_operaciones=("facturacion_registrada_operaciones", "sum"),
        costo_real_comercial=("costo_real_comercial", "sum"),
        costo_dw_real=("costo_dw_real", "sum"),
        costo_real_operaciones=("costo_real_operaciones", "sum"),
        margen_real=("margen_real", "sum"),
    ).reset_index()
    if mode == "servicios":
        ordered = [
            "pais", "proyecto", "horas_estimadas", "horas_registradas", "horas_facturables",
            "facturacion_estimada_operaciones", "facturacion_registrada_operaciones", "costo_real_operaciones",
        ]
    else:
        ordered = [
            "pais", "proyecto", "horas_estimadas", "horas_registradas", "horas_facturables",
            "facturacion_estimada", "facturacion_registrada", "costo_real_comercial", "costo_real_operaciones", "margen_real",
        ]
    return agg[[c for c in ordered if c in agg.columns]].sort_values(["pais", "proyecto"])


def build_detail(df: pd.DataFrame, mode: str = "general") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    group_cols = ["pais", "cliente", "proyecto", "assignee", "rol_estimado", "rol_asignado"]
    agg = df.groupby(group_cols, dropna=False).agg(
        rol_comercial_asignado=("rol_comercial_asignado", "first"),
        horas_estimadas=("horas_estimadas", "sum"),
        horas_registradas=("horas_registradas", "sum"),
        horas_facturables=("horas_facturables", "sum"),
        tarifa_real_dw_hora=("tarifa_real_dw_hora", "first"),
        tarifa_facturable_hora=("tarifa_facturable_hora", "first"),
        facturacion_estimada=("facturacion_estimada", "sum"),
        facturacion_registrada=("facturacion_registrada", "sum"),
        facturacion_real=("facturacion_real", "sum"),
        facturacion_estimada_operaciones=("facturacion_estimada_operaciones", "sum"),
        facturacion_registrada_operaciones=("facturacion_registrada_operaciones", "sum"),
        costo_real_comercial=("costo_real_comercial", "sum"),
        costo_dw_real=("costo_dw_real", "sum"),
        costo_real_operaciones=("costo_real_operaciones", "sum"),
        margen_real=("margen_real", "sum"),
    ).reset_index().rename(columns={"assignee": "persona"})
    agg["margen_pct"] = agg.apply(lambda r: _weighted_rate(r["margen_real"], r["costo_real_comercial"]), axis=1)
    if mode == "servicios":
        ordered = [
            "pais", "cliente", "proyecto", "persona", "rol_estimado", "rol_asignado",
            "horas_estimadas", "horas_registradas", "horas_facturables",
            "tarifa_real_dw_hora", "facturacion_estimada_operaciones",
            "facturacion_registrada_operaciones", "costo_real_operaciones",
        ]
    else:
        ordered = [
            "pais", "cliente", "proyecto", "persona", "rol_estimado", "rol_asignado",
            "horas_estimadas", "horas_registradas", "horas_facturables",
            "tarifa_real_dw_hora", "tarifa_facturable_hora", "facturacion_estimada", "facturacion_registrada",
            "costo_real_comercial", "costo_real_operaciones", "margen_real",
        ]
    return agg[[c for c in ordered if c in agg.columns]].sort_values(["pais", "cliente", "proyecto", "persona"])


def filter_dataframe(df: pd.DataFrame, pais: str | None = None, cliente: str | None = None, proyecto: str | None = None, hito: str | None = None, fecha_inicio: date | None = None, fecha_fin: date | None = None) -> pd.DataFrame:
    out = df.copy()
    for col, value in [("pais", pais), ("cliente", cliente), ("proyecto", proyecto), ("hito_facturable", hito)]:
        if value and value != "Todos":
            out = out[out[col].fillna("").astype(str) == value]
    if fecha_inicio is not None:
        out = out[pd.to_datetime(out["fecha_referencia"], errors="coerce") >= pd.to_datetime(fecha_inicio)]
    if fecha_fin is not None:
        out = out[pd.to_datetime(out["fecha_referencia"], errors="coerce") <= pd.to_datetime(fecha_fin)]
    return out


def options_from(df: pd.DataFrame, col: str) -> list[str]:
    if df.empty or col not in df.columns:
        return ["Todos"]
    vals = sorted([str(x) for x in df[col].dropna().unique() if str(x).strip() != ""])
    return ["Todos"] + vals


def project_progress(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    prog = df.groupby(["pais", "cliente", "proyecto"], dropna=False).agg(
        horas_estimadas=("horas_estimadas", "sum"),
        horas_registradas=("horas_registradas", "sum"),
        horas_facturables=("horas_facturables", "sum"),
        costo_real_comercial=("costo_real_comercial", "sum"),
        costo_real_operaciones=("costo_real_operaciones", "sum"),
        margen_real=("margen_real", "sum"),
    ).reset_index()
    prog["avance_horas"] = prog.apply(lambda r: r["horas_registradas"] / r["horas_estimadas"] if r["horas_estimadas"] else 0, axis=1)
    prog["margen_pct"] = prog.apply(lambda r: r["margen_real"] / r["costo_real_comercial"] if r["costo_real_comercial"] else 0, axis=1)
    return prog.sort_values("avance_horas", ascending=False)
