from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

import pandas as pd

CANONICAL_COLUMNS = {
    "task_id": ["task id", "id tarea", "id de tarea"],
    "task_name": ["task name", "nombre de tarea", "tarea"],
    "parent_id": ["parent id", "id padre"],
    "parent_name": ["parent name", "nombre padre"],
    "assignee": ["assignee", "assigned to", "persona", "consultor", "responsable"],
    "fecha_referencia": ["due date", "fecha", "fecha referencia", "fecha de registro", "time entry date"],
    "pais": ["país (drop down)", "pais (drop down)", "país", "pais", "country"],
    "cliente": ["cliente (drop down)", "cliente", "client"],
    "proyecto": ["proyecto (drop down)", "proyecto", "project"],
    "hito_facturable": ["hitos facturable (drop down)", "hito facturable", "hitos facturable", "milestone", "hito"],
    "rol": ["rol (drop down)", "rol", "rol interno", "role"],
    "rol_facturable": ["rol facturable (drop down)", "rol facturable", "billable role"],
    "status": ["status", "estado"],
    "task_type": ["task type", "tipo de tarea"],
    "horas_estimadas": ["time estimate", "horas estimadas", "estimate"],
    "horas_registradas": ["time logged", "horas registradas", "logged"],
    "horas_facturables": ["horas facturables (number)", "horas facturables", "facturable", "billable hours"],
}

ROLLED_UP_COLUMNS = [
    "time estimate rolled up",
    "time logged rolled up",
]

# En algunos exportes de ClickUp, las celdas visualmente vacías pueden llegar con
# el texto/valor "24" en campos categóricos. No debe interpretarse como consultor,
# rol, país, cliente ni proyecto. Esta regla se aplica solo a textos, no a horas.
TEXT_PLACEHOLDERS = {"", "nan", "none", "null", "-", "24"}
HITO_NO_APLICA = "No aplica"
ROLES_FACTURABLES_FIJOS = ["Jefe de proyecto", "Senior", "Semisenior", "Junior"]


FACTURABLE_MODES = {
    "excel_or_logged": "Usar Horas facturables del Excel; si está vacío, usar Horas registradas",
    "excel_only": "Usar solo Horas facturables del Excel",
    "logged_only": "Usar Horas registradas como Horas facturables",
    "zero_if_blank": "Dejar en cero si Horas facturables está vacío",
}


def normalize_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n",
        "ü": "u",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_hito(value: Any) -> str:
    text = clean_string(value) if 'clean_string' in globals() else ("" if value is None else str(value).strip())
    if normalize_text(text) in {"", "empty", "sin hito", "no aplica", "n/a", "na", "nan", "none", "null", "-"}:
        return HITO_NO_APLICA
    return text


def canonicalize_facturable_role(value: Any) -> str:
    key = normalize_text(value)
    aliases = {
        "jefe de proyecto": "Jefe de proyecto",
        "jefe proyecto": "Jefe de proyecto",
        "project manager": "Jefe de proyecto",
        "pm": "Jefe de proyecto",
        "senior": "Senior",
        "sr": "Senior",
        "junior": "Junior",
        "jr": "Junior",
        "semisenior": "Semisenior",
        "semi senior": "Semisenior",
        "semi-senior": "Semisenior",
        "ssr": "Semisenior",
    }
    return aliases.get(key, "")


def canonicalize_internal_role(value: Any) -> str:
    fixed = canonicalize_facturable_role(value)
    return fixed or clean_string(value)

def _mode_non_empty(values: pd.Series) -> str:
    cleaned = [str(v).strip() for v in values.tolist() if str(v).strip()]
    if not cleaned:
        return ""
    return pd.Series(cleaned).mode().iloc[0]


def infer_missing_roles(mapped: pd.DataFrame) -> pd.DataFrame:
    """Completa roles vacíos a partir de patrones del mismo Excel.

    Prioridad de inferencia:
    1. mismo consultor + proyecto + hito;
    2. mismo consultor + proyecto;
    3. mismo consultor.

    Esto corrige tareas operativas donde ClickUp trae horas y consultor, pero no arrastra el rol.
    """
    mapped = mapped.copy()
    if mapped.empty:
        return mapped

    def build_lookup(keys: list[str], value_col: str) -> dict[tuple, str]:
        if not all(k in mapped.columns for k in keys) or value_col not in mapped.columns:
            return {}
        tmp = mapped[mapped[value_col].fillna("").astype(str).str.strip() != ""].copy()
        if tmp.empty:
            return {}
        grouped = tmp.groupby(keys, dropna=False)[value_col].apply(_mode_non_empty).reset_index()
        return {tuple(str(row[k]).strip() for k in keys): str(row[value_col]).strip() for _, row in grouped.iterrows()}

    for value_col in ["rol", "rol_facturable"]:
        lookups = [
            (["assignee", "proyecto", "hito_facturable"], build_lookup(["assignee", "proyecto", "hito_facturable"], value_col)),
            (["assignee", "proyecto"], build_lookup(["assignee", "proyecto"], value_col)),
            (["assignee"], build_lookup(["assignee"], value_col)),
        ]
        for idx, row in mapped[mapped[value_col].fillna("").astype(str).str.strip().eq("")].iterrows():
            for keys, lookup in lookups:
                key = tuple(str(row.get(k, "")).strip() for k in keys)
                val = lookup.get(key, "")
                if val:
                    mapped.at[idx, value_col] = val
                    break

    mapped["rol_facturable"] = mapped.apply(
        lambda r: canonicalize_facturable_role(r["rol_facturable"]) or canonicalize_facturable_role(r["rol"]),
        axis=1,
    )
    mapped["rol"] = mapped.apply(lambda r: canonicalize_internal_role(r["rol"]) or r["rol_facturable"], axis=1)
    return mapped



def _find_header_row(raw: pd.DataFrame) -> int:
    for idx, row in raw.iterrows():
        normalized = [normalize_text(v) for v in row.tolist()]
        if "task id" in normalized and any(v in normalized for v in ["task name", "nombre de tarea"]):
            return int(idx)
    # Fallback: first row with at least 5 non-empty values
    counts = raw.notna().sum(axis=1)
    candidates = counts[counts >= 5]
    if len(candidates) > 0:
        return int(candidates.index[0])
    return 0


def read_clickup_excel(uploaded_file: Any, sheet_name: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Lee el Excel de ClickUp aunque tenga filas de título antes del encabezado real."""
    if hasattr(uploaded_file, "read"):
        content = uploaded_file.read()
        bio = BytesIO(content)
    else:
        bio = uploaded_file

    xls = pd.ExcelFile(bio)
    selected_sheet = sheet_name or ("Tasks" if "Tasks" in xls.sheet_names else xls.sheet_names[0])

    raw = pd.read_excel(xls, sheet_name=selected_sheet, header=None)
    header_row = _find_header_row(raw)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    if isinstance(bio, BytesIO):
        bio.seek(0)
    df = pd.read_excel(bio, sheet_name=selected_sheet, header=header_row)
    df = df.dropna(how="all").reset_index(drop=True)
    metadata = {"sheet_name": selected_sheet, "header_row_excel": header_row + 1, "sheet_names": xls.sheet_names}
    return df, metadata


def _resolve_column(df: pd.DataFrame, canonical: str) -> str | None:
    normalized_cols = {normalize_text(c): c for c in df.columns}
    targets = [normalize_text(x) for x in CANONICAL_COLUMNS[canonical]]
    for target in targets:
        if target in normalized_cols:
            return normalized_cols[target]
    # Búsqueda flexible por inclusión, evitando usar columnas rolled up para horas base.
    for norm_col, original in normalized_cols.items():
        if canonical in ["horas_estimadas", "horas_registradas"] and norm_col in ROLLED_UP_COLUMNS:
            continue
        for target in targets:
            if target and (target in norm_col or norm_col in target):
                return original
    return None


def detect_column_mapping(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labels = {
        "task_id": "ID de tarea",
        "task_name": "Nombre de tarea",
        "parent_id": "ID padre",
        "parent_name": "Nombre padre",
        "assignee": "Persona asignada",
        "fecha_referencia": "Fecha de referencia",
        "pais": "País",
        "cliente": "Cliente",
        "proyecto": "Proyecto",
        "hito_facturable": "Hito facturable",
        "rol": "Rol interno",
        "rol_facturable": "Rol facturable",
        "status": "Estado",
        "task_type": "Tipo de tarea",
        "horas_estimadas": "Horas estimadas",
        "horas_registradas": "Horas registradas",
        "horas_facturables": "Horas facturables",
    }
    for canonical in CANONICAL_COLUMNS:
        rows.append({
            "Dato del sistema": labels.get(canonical, canonical),
            "Columna detectada en Excel": _resolve_column(df, canonical) or "NO DETECTADA",
        })
    return pd.DataFrame(rows)


def parse_hours(value: Any) -> float:
    """Convierte horas desde textos tipo '1h 30m', '90m', '1:30', '1722h' o números."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        val = float(value)
        # ClickUp API suele usar milisegundos. En Excel puede venir como horas.
        if val > 100_000:
            return round(val / 3_600_000, 4)
        return round(val, 4)
    text = str(value).strip().lower()
    if text in {"", "nan", "none", "null", "-"}:
        return 0.0
    text = text.replace(",", ".")
    # Formato HH:MM o HH:MM:SS
    if re.fullmatch(r"\d{1,4}:\d{1,2}(:\d{1,2})?", text):
        parts = [float(p) for p in text.split(":")]
        if len(parts) == 2:
            return round(parts[0] + parts[1] / 60, 4)
        return round(parts[0] + parts[1] / 60 + parts[2] / 3600, 4)
    hours = 0.0
    h_match = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*h", text)
    m_match = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*m", text)
    s_match = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*s", text)
    if h_match or m_match or s_match:
        hours += sum(float(x) for x in h_match)
        hours += sum(float(x) for x in m_match) / 60
        hours += sum(float(x) for x in s_match) / 3600
        return round(hours, 4)
    numeric = re.findall(r"-?\d+(?:\.\d+)?", text)
    if numeric:
        return round(float(numeric[0]), 4)
    return 0.0


def parse_date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Fecha serial Excel. 1899-12-30 corrige el bug histórico de Excel.
        if 25_000 <= float(value) <= 80_000:
            return (pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")).date().isoformat()
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def clean_string(value: Any, *, treat_clickup_placeholder: bool = True) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if treat_clickup_placeholder and normalize_text(text) in TEXT_PLACEHOLDERS:
        return ""
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _is_probable_clickup_task_id(value: Any) -> bool:
    text = clean_string(value, treat_clickup_placeholder=False)
    if not text:
        return False
    if normalize_text(text) in {"task id", "id tarea", "id de tarea", "empty"}:
        return False
    # IDs de ClickUp suelen ser alfanuméricos compactos, pero no forzamos demasiado.
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{5,}", text))


def _build_data_alert(row: pd.Series, original_horas_facturables: float, mode: str) -> str:
    alerts: list[str] = []
    if not row.get("assignee"):
        alerts.append("Sin consultor")
    if not row.get("rol"):
        alerts.append("Sin rol interno")
    if not row.get("rol_facturable"):
        alerts.append("Sin rol facturable válido")
    if not row.get("fecha_referencia"):
        alerts.append("Sin fecha de referencia")
    if mode == "excel_or_logged" and original_horas_facturables == 0 and float(row.get("horas_registradas") or 0) > 0:
        alerts.append("Horas facturables tomadas de horas registradas")
    return "; ".join(alerts)


def transform_clickup_dataframe(
    df: pd.DataFrame,
    id_carga: int,
    facturable_mode: str = "excel_or_logged",
) -> pd.DataFrame:
    """Normaliza el Excel de ClickUp a la estructura del sistema.

    Regla de horas corregida:
    - Se usan las columnas base Time Estimate y Time Logged.
    - No se usan columnas Rolled Up para los cálculos por tarea.
    - Se incluyen las filas con Task Type = Task, aunque sean tareas padre, porque su Time Estimate/Logged
      representa horas propias de esa tarea; así no se pierden horas.
    - Se excluyen filas de grupo, encabezados repetidos, Proyecto y Milestone para evitar doble conteo.
    - Si el hito viene vacío, se guarda como "No aplica".
    - Para calcular tarifas se exige consultor, rol interno y rol facturable.
    - Los roles facturables se normalizan a: Jefe de proyecto, Senior, Semisenior y Junior.
    """
    if facturable_mode not in FACTURABLE_MODES:
        facturable_mode = "excel_or_logged"

    mapped = pd.DataFrame()
    raw_records = df.fillna("").astype(str).to_dict(orient="records")
    for canonical in CANONICAL_COLUMNS:
        source_col = _resolve_column(df, canonical)
        if source_col is None:
            mapped[canonical] = None
        else:
            mapped[canonical] = df[source_col]

    text_cols = [
        "task_id", "task_name", "parent_id", "parent_name", "assignee", "pais", "cliente", "proyecto",
        "hito_facturable", "rol", "rol_facturable", "status", "task_type"
    ]
    for col in text_cols:
        mapped[col] = mapped[col].apply(clean_string)

    # Regla funcional: si no hay hito, se guarda explícitamente como "No aplica".
    # Esto evita que el resumen y las tarifas comerciales trabajen con blancos.
    mapped["hito_facturable"] = mapped["hito_facturable"].apply(normalize_hito)

    # Roles facturables cerrados: Jefe de proyecto, Senior, Semisenior y Junior.
    # Si el Excel trae el rol facturable vacío, se intenta tomar el rol interno como respaldo.
    mapped["rol_facturable"] = mapped.apply(
        lambda r: canonicalize_facturable_role(r["rol_facturable"]) or canonicalize_facturable_role(r["rol"]),
        axis=1,
    )
    mapped["rol"] = mapped.apply(
        lambda r: canonicalize_internal_role(r["rol"]) or r["rol_facturable"], axis=1
    )
    mapped = infer_missing_roles(mapped)

    mapped["_raw_json"] = [json.dumps(r, ensure_ascii=False) for r in raw_records]

    # Elimina encabezados repetidos y filas de grupo/separador. En el Excel de ClickUp aparecen
    # filas como "Proyecto Migración CGONOS" o "Empty" en la primera columna sin Task Name.
    repeated_header = (
        mapped["task_id"].apply(normalize_text).isin({"task id", "id tarea", "id de tarea"})
        | mapped["task_name"].apply(normalize_text).isin({"task name", "nombre de tarea"})
        | mapped["pais"].apply(normalize_text).isin({"pais (drop down)", "pais", "country"})
        | mapped["proyecto"].apply(normalize_text).isin({"proyecto (drop down)", "project"})
    )
    no_task_name = mapped["task_name"].astype(str).str.strip().eq("")
    no_valid_task_id = ~mapped["task_id"].apply(_is_probable_clickup_task_id)
    mapped = mapped.loc[~repeated_header & ~no_task_name & ~no_valid_task_id].reset_index(drop=True)

    mapped["fecha_referencia"] = mapped["fecha_referencia"].apply(parse_date)
    mapped["horas_estimadas"] = mapped["horas_estimadas"].apply(parse_hours)
    mapped["horas_registradas"] = mapped["horas_registradas"].apply(parse_hours)
    original_facturable = mapped["horas_facturables"].apply(parse_hours)

    if facturable_mode == "excel_only" or facturable_mode == "zero_if_blank":
        mapped["horas_facturables"] = original_facturable
        mapped["fuente_horas_facturables"] = original_facturable.apply(lambda x: "Excel" if x > 0 else "Vacío/0 en Excel")
    elif facturable_mode == "logged_only":
        mapped["horas_facturables"] = mapped["horas_registradas"]
        mapped["fuente_horas_facturables"] = "Horas registradas"
    else:
        mapped["horas_facturables"] = original_facturable.where(original_facturable > 0, mapped["horas_registradas"])
        mapped["fuente_horas_facturables"] = original_facturable.apply(lambda x: "Excel" if x > 0 else "Fallback a horas registradas")

    # Regla anti-duplicidad corregida: como NO usamos columnas Rolled Up, sí se deben incluir
    # tareas padre de tipo Task con horas propias. Solo se excluyen contenedores Proyecto/Milestone/List/Folder.
    task_type_norm = mapped["task_type"].apply(normalize_text)
    is_container_type = task_type_norm.isin({"proyecto", "project", "milestone", "hito", "folder", "list"})
    has_business_hours = (mapped["horas_estimadas"] + mapped["horas_registradas"] + mapped["horas_facturables"]) > 0
    has_required_dimensions = (
        mapped["assignee"].fillna("").astype(str).str.strip().ne("")
        & mapped["rol"].fillna("").astype(str).str.strip().ne("")
        & mapped["rol_facturable"].fillna("").astype(str).str.strip().ne("")
    )

    if task_type_norm.eq("task").any():
        mapped["es_fila_calculable"] = (task_type_norm.eq("task") & has_business_hours & has_required_dimensions).astype(int)
    else:
        mapped["es_fila_calculable"] = (~is_container_type & has_business_hours & has_required_dimensions).astype(int)

    mapped["regla_limpieza"] = mapped.apply(
        lambda r: "Incluida: tarea operativa con horas, consultor y rol" if int(r["es_fila_calculable"]) == 1
        else ("Excluida: falta consultor/rol para calcular tarifas" if (float(r["horas_estimadas"] or 0) + float(r["horas_registradas"] or 0) + float(r["horas_facturables"] or 0)) > 0 else "Excluida: proyecto/milestone/lista/fila sin horas"),
        axis=1,
    )

    mapped["alerta_datos"] = [
        _build_data_alert(row, float(orig or 0), facturable_mode)
        for (_, row), orig in zip(mapped.iterrows(), original_facturable.tolist())
    ]

    mapped["id_carga"] = id_carga
    mapped["raw_json"] = mapped["_raw_json"]

    return mapped[
        [
            "id_carga", "task_id", "task_name", "parent_id", "parent_name", "assignee", "fecha_referencia",
            "pais", "cliente", "proyecto", "hito_facturable", "rol", "rol_facturable", "status", "task_type",
            "horas_estimadas", "horas_registradas", "horas_facturables", "fuente_horas_facturables",
            "es_fila_calculable", "regla_limpieza", "alerta_datos", "raw_json"
        ]
    ]
