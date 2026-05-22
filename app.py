from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from dw_manager.calculations import (
    apply_tariffs,
    build_detail,
    build_summary,
    filter_dataframe,
    options_from,
    project_progress,
    total_metrics,
)
from dw_manager.db import (
    ROLES_FACTURABLES_FIJOS,
    create_carga,
    get_connection,
    get_latest_carga_id,
    init_db,
    insert_registros,
    list_cargas,
    list_proyectos_catalogo,
    list_role_names,
    load_registros,
    load_tarifas_comerciales,
    load_tarifas_dw,
    seed_catalogs_from_registros,
    set_carga_estado,
    upsert_tarifa_comercial,
    upsert_tarifa_dw,
)
from dw_manager.excel_parser import read_clickup_excel, transform_clickup_dataframe
from dw_manager.export import dataframe_to_excel_bytes

DB_PATH = Path("data") / "dw_clickup.sqlite3"

st.set_page_config(
    page_title="DW Manager | Horas y Resultado Operativo",
    page_icon="☰",
    layout="wide",
    initial_sidebar_state="expanded",
)

conn = get_connection(DB_PATH)
init_db(conn)

# -----------------------------------------------------------------------------
# Estilo visual
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    :root{
        --navy:#0b1220; --navy2:#111827; --blue:#2563eb; --cyan:#06b6d4;
        --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --soft:#f8fafc;
        --green:#059669; --red:#dc2626; --amber:#d97706;
        --shadow:0 18px 50px rgba(15,23,42,.08);
    }
    html, body, [class*="css"] {font-family:'Inter',system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif!important;}
    body,.stApp{background:radial-gradient(circle at top left,rgba(37,99,235,.08),transparent 30rem),#f5f7fb!important;color:var(--ink);}
    .block-container{padding-top:1.1rem;padding-bottom:3rem;max-width:1500px;}
    header[data-testid="stHeader"]{background:transparent!important;} #MainMenu, footer{visibility:hidden;}

    [data-testid="stSidebar"]{background:linear-gradient(180deg,#0b1220 0%,#111827 100%)!important;border-right:1px solid rgba(148,163,184,.18);}
    [data-testid="stSidebar"] *{color:#e5e7eb!important;}
    [data-testid="stSidebar"] .block-container{padding-top:1rem;}
    .brand-card{background:linear-gradient(135deg,rgba(255,255,255,.12),rgba(255,255,255,.045));border:1px solid rgba(255,255,255,.14);border-radius:24px;padding:1rem;margin-bottom:1rem;box-shadow:0 22px 45px rgba(0,0,0,.18);}
    .brand-row{display:flex;align-items:center;gap:.75rem}.brand-logo{width:42px;height:42px;border-radius:16px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#2563eb,#06b6d4);font-weight:900;color:white!important;}
    .brand-title{font-size:1.1rem;font-weight:900;color:#fff!important;letter-spacing:-.03em}.brand-subtitle{font-size:.74rem;color:#cbd5e1!important;margin-top:.05rem}.brand-pill{margin-top:.8rem;display:inline-flex;padding:.38rem .65rem;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);font-size:.72rem;font-weight:800;}
    [data-testid="stSidebar"] [role="radiogroup"]{display:flex;flex-direction:column;gap:.42rem;}
    [data-testid="stSidebar"] [role="radiogroup"] label{padding:.72rem .85rem!important;border-radius:16px!important;background:rgba(255,255,255,.045)!important;border:1px solid rgba(255,255,255,.055)!important;margin:0!important;cursor:pointer;transition:all .16s ease;display:flex!important;align-items:center!important;gap:.55rem!important;}
    [data-testid="stSidebar"] [role="radiogroup"] label:hover{background:rgba(255,255,255,.11)!important;transform:translateX(3px);}
    [data-testid="stSidebar"] [role="radiogroup"] label p{font-size:.9rem!important;font-weight:800!important;margin:0!important;color:#e5e7eb!important;}
    [data-testid="stSidebar"] [aria-checked="true"]{background:linear-gradient(135deg,rgba(37,99,235,.95),rgba(6,182,212,.75))!important;border-color:rgba(191,219,254,.45)!important;box-shadow:0 16px 28px rgba(37,99,235,.22);}

    .page-hero{background:linear-gradient(135deg,#fff,rgba(239,246,255,.94));border:1px solid rgba(226,232,240,.9);border-radius:28px;padding:1.25rem 1.35rem;margin-bottom:1rem;box-shadow:var(--shadow);}
    .page-title{font-size:1.65rem;font-weight:900;letter-spacing:-.04em;color:#0f172a}.page-subtitle{margin-top:.28rem;color:#64748b;font-weight:600;font-size:.92rem;}
    .soft-card{background:#fff;border:1px solid #e5e7eb;border-radius:24px;padding:1.1rem;margin:.7rem 0 1rem;box-shadow:0 10px 30px rgba(15,23,42,.055);}
    .formula-grid,.flow-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.75rem;}
    .mini-note{background:#f8fafc;border:1px solid #e2e8f0;border-radius:18px;padding:.85rem;color:#334155;font-weight:650;}.mini-note span{color:#64748b;font-weight:500;font-size:.85rem;}
    .metric-card{background:#fff;border:1px solid #e5e7eb;border-radius:24px;padding:1.15rem;box-shadow:0 10px 30px rgba(15,23,42,.055);min-height:126px;margin-bottom:1rem;}
    .metric-top{display:flex;justify-content:space-between;align-items:center}.metric-label{color:#64748b;font-size:.8rem;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.metric-icon{width:30px;height:30px;border-radius:11px;background:#eff6ff;color:#2563eb!important;display:flex;align-items:center;justify-content:center;font-weight:900}.metric-value{font-size:1.65rem;font-weight:900;letter-spacing:-.04em;margin-top:.6rem;color:#0f172a}.metric-sub{font-size:.8rem;color:#64748b;margin-top:.2rem;font-weight:600}.good{color:#059669!important}.bad{color:#dc2626!important;}
    .section-head{margin-top:1.1rem;margin-bottom:.55rem}.section-title-wrap{display:flex;align-items:center;gap:.7rem}.section-icon{width:34px;height:34px;border-radius:13px;background:#e0f2fe;color:#0369a1;display:flex;align-items:center;justify-content:center;font-weight:900}.section-title{font-size:1.1rem;font-weight:900;letter-spacing:-.025em}.section-subtitle{font-size:.82rem;color:#64748b;font-weight:600;}
    .upload-empty{border:1.5px dashed #cbd5e1;background:#fff;border-radius:28px;padding:3rem;text-align:center;box-shadow:var(--shadow)}.upload-icon{font-size:2.5rem;margin-bottom:.3rem;}
    .progress-card{background:#fff;border:1px solid #e5e7eb;border-radius:22px;padding:1rem;margin:.55rem 0;box-shadow:0 8px 24px rgba(15,23,42,.045)}.progress-title{display:flex;justify-content:space-between;font-weight:900}.progress-name{color:#0f172a}.progress-pct{color:#2563eb}.track{height:12px;background:#e5e7eb;border-radius:999px;margin:.75rem 0;overflow:hidden}.bar{height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#06b6d4)}.progress-meta{display:flex;justify-content:space-between;gap:.6rem;flex-wrap:wrap;color:#64748b;font-size:.85rem;font-weight:650;}
    div[data-testid="stDataFrame"]{border-radius:18px;overflow:hidden;border:1px solid #e5e7eb;box-shadow:0 10px 28px rgba(15,23,42,.045)}
    .app-footer{color:#94a3b8;font-size:.75rem;margin-top:1.2rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Utilidades visuales
# -----------------------------------------------------------------------------

def money(v: float | int | None) -> str:
    return f"US$ {float(v or 0):,.2f}"


def hours(v: float | int | None) -> str:
    return f"{float(v or 0):,.2f} h"


def pct(v: float | int | None) -> str:
    return f"{float(v or 0) * 100:,.1f}%"


DISPLAY_NAMES = {
    "id_carga": "ID carga", "nombre_archivo": "Archivo", "descripcion": "Descripción", "fecha_carga": "Fecha de carga", "total_filas": "Filas totales", "filas_calculables": "Filas calculables", "usuario_carga": "Responsable", "estado": "Estado",
    "pais": "País", "cliente": "Cliente", "proyecto": "Proyecto", "hito_facturable": "Hito facturable", "assignee": "Persona", "persona": "Persona",
    "rol": "Rol estimado", "rol_estimado": "Rol estimado", "rol_asignado": "Rol asignado", "rol_facturable": "Rol asignado", "rol_comercial_asignado": "Rol asignado",
    "horas_estimadas": "Horas estimadas", "horas_registradas": "Horas registradas", "horas_facturables": "Horas facturables",
    "tarifa_real_dw_hora": "Tarifa operaciones/hora", "tarifa_operaciones_hora": "Tarifa operaciones/hora", "tarifa_facturable_hora": "Tarifa comercial/hora", "tarifa_comercial_hora": "Tarifa comercial/hora",
    "rol_interno": "Rol interno", "rol_tarifa_operaciones": "Rol tarifa operaciones", "rol_tarifa_comercial": "Rol tarifa comercial", "proyecto_tarifa_comercial": "Proyecto tarifa comercial",
    "facturacion_estimada": "Facturación estimada comercial", "facturacion_registrada": "Facturación registrada comercial", "facturacion_real": "Costo real comercial", "costo_real_comercial": "Costo real comercial",
    "facturacion_estimada_operaciones": "Facturación estimada operaciones", "facturacion_registrada_operaciones": "Facturación registrada operaciones",
    "costo_dw_real": "Costo real operaciones", "costo_real_operaciones": "Costo real operaciones", "margen_real": "Resultado operativo", "resultado_operativo": "Resultado operativo", "margen_pct": "Resultado operativo %", "progreso": "Progreso",
    "moneda": "Moneda", "fecha_inicio_vigencia": "Fecha inicio", "fecha_fin_vigencia": "Fecha fin", "usuario_registro": "Usuario", "fecha_registro": "Fecha registro", "observacion": "Observación",
    "id_tarifa_dw": "ID tarifa operaciones", "id_tarifa_comercial": "ID tarifa comercial", "task_name": "Tarea", "fecha_referencia": "Fecha de referencia", "status": "Estado ClickUp", "task_type": "Tipo de tarea", "fuente_horas_facturables": "Fuente horas facturables", "alerta_tarifa": "Alerta de tarifa",
}


def present_df(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    out = df.rename(columns={c: DISPLAY_NAMES.get(c, c.replace("_", " ").title()) for c in df.columns}).copy()
    # Evita errores de Streamlit/Pandas Styler cuando dos columnas terminan con el mismo nombre visible.
    seen: dict[str, int] = {}
    unique_cols: list[str] = []
    for col in out.columns:
        base = str(col)
        if base not in seen:
            seen[base] = 0
            unique_cols.append(base)
        else:
            seen[base] += 1
            unique_cols.append(f"{base} ({seen[base] + 1})")
    out.columns = unique_cols
    return out.reset_index(drop=True)


def table_style(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    if df is None or df.empty:
        return pd.DataFrame().style
    out = present_df(df)
    numeric_cols = {c for c in out.columns if pd.api.types.is_numeric_dtype(out[c])}
    fmt: dict[str, str] = {}
    for c in out.columns:
        if c not in numeric_cols:
            continue
        low = c.lower()
        if low.startswith("id") or low == "estado":
            continue
        if "%" in low or "progreso" in low:
            fmt[c] = "{:.1%}"
        elif any(x in low for x in ["tarifa", "facturación", "costo", "resultado operativo"]):
            fmt[c] = "US$ {:,.2f}"
        elif "hora" in low:
            fmt[c] = "{:,.2f}"
    return out.style.format(fmt, na_rep="-").set_properties(**{"font-size": "12.5px"})


def show_table(df: pd.DataFrame | None, height: int = 360) -> None:
    if df is None or df.empty:
        st.info("No hay registros para mostrar.")
        return
    st.dataframe(table_style(df), use_container_width=True, hide_index=True, height=height)


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f"""
        <div class="page-hero">
            <div class="page-title">{title}</div>
            <div class="page-subtitle">{subtitle}</div>
        </div>
    """, unsafe_allow_html=True)


def metric_card(label: str, value: str, sub: str = "", kind: str = "") -> None:
    icon = "$" if any(x in label.lower() for x in ["facturación", "costo", "resultado"]) else "h" if "hora" in label.lower() else "▦"
    cls = "good" if kind == "good" else "bad" if kind == "bad" else ""
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-top"><div class="metric-label">{label}</div><div class="metric-icon">{icon}</div></div>
        <div class="metric-value {cls}">{value}</div>
        <div class="metric-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


def section_title(title: str, subtitle: str = "", icon: str = "▸") -> None:
    st.markdown(f"""
    <div class="section-head"><div class="section-title-wrap"><div class="section-icon">{icon}</div><div><div class="section-title">{title}</div><div class="section-subtitle">{subtitle}</div></div></div></div>
    """, unsafe_allow_html=True)


def date_range_from(df: pd.DataFrame) -> tuple[date, date]:
    fechas = pd.to_datetime(df.get("fecha_referencia"), errors="coerce").dropna()
    if fechas.empty:
        today = date.today()
        return today, today
    return fechas.min().date(), fechas.max().date()


def default_tariff_dates() -> tuple[date, date]:
    try:
        row = conn.execute("SELECT MIN(date(fecha_referencia)) FROM registros_clickup WHERE es_fila_calculable=1").fetchone()
        start = pd.to_datetime(row[0]).date() if row and row[0] else date(date.today().year, 1, 1)
    except Exception:
        start = date(date.today().year, 1, 1)
    return start, date(2099, 12, 31)


def selected_carga() -> tuple[int | None, str | None]:
    cargas = list_cargas(conn)
    if cargas.empty:
        return None, None
    activas = cargas[cargas["estado"] == "ACTIVA"].copy()
    if activas.empty:
        return None, None
    latest = get_latest_carga_id(conn)
    opts = {f"{int(r.id_carga)} | {r.nombre_archivo} | {r.fecha_carga}": int(r.id_carga) for _, r in activas.iterrows()}
    default = next((k for k, v in opts.items() if v == latest), list(opts.keys())[0])
    label = st.selectbox("Carga", list(opts.keys()), index=list(opts.keys()).index(default))
    return opts[label], label


def project_label(row: pd.Series) -> str:
    return f"{int(row.id_proyecto_catalogo)} | {row.pais} | {row.cliente} | {row.proyecto}"


def _tarifas_operaciones_presentables() -> pd.DataFrame:
    df = load_tarifas_dw(conn)
    if df.empty:
        return df
    return df[[c for c in ["id_tarifa_dw", "rol_interno", "tarifa_real_dw_hora", "moneda", "estado", "usuario_registro", "observacion"] if c in df.columns]]


def _tarifas_comerciales_presentables() -> pd.DataFrame:
    df = load_tarifas_comerciales(conn)
    if df.empty:
        return df
    return df[[c for c in ["id_tarifa_comercial", "cliente", "proyecto", "rol_facturable", "tarifa_comercial_hora", "moneda", "estado", "usuario_registro", "observacion"] if c in df.columns]]

# -----------------------------------------------------------------------------
# Páginas
# -----------------------------------------------------------------------------

def page_inicio() -> None:
    page_header("DW Manager", "Mini sistema conectado para horas, tarifas y resultado operativo.")
    cargas = list_cargas(conn)
    proyectos = list_proyectos_catalogo(conn, only_active=False)
    t_ops = load_tarifas_dw(conn)
    t_com = load_tarifas_comerciales(conn)

    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Cargas", f"{len(cargas):,}", "Archivos ClickUp guardados")
    with c2: metric_card("Proyectos", f"{len(proyectos):,}", "Detectados desde ClickUp")
    with c3: metric_card("Tarifas operaciones", f"{len(t_ops):,}", "Por rol interno")
    with c4: metric_card("Tarifas comerciales", f"{len(t_com):,}", "Por proyecto y rol")

    st.markdown("""
    <div class="soft-card">
        <h3 style="margin-top:0;">Flujo del mini sistema</h3>
        <div class="flow-grid">
            <div class="mini-note"><b>1</b><br>Excel ClickUp<br><span>país, cliente, proyecto, hito, roles y horas</span></div>
            <div class="mini-note"><b>2</b><br>Tarifa operaciones<br><span>siempre por rol interno</span></div>
            <div class="mini-note"><b>3</b><br>Tarifa comercial<br><span>por proyecto y rol asignado</span></div>
            <div class="mini-note"><b>4</b><br>Gerencia<br><span>horas × tarifas y resultado operativo</span></div>
        </div>
    </div>
    <div class="soft-card">
        <h3 style="margin-top:0;">Reglas de cálculo</h3>
        <div class="formula-grid">
            <div><b>Facturación estimada comercial</b><br><span>Horas estimadas × Tarifa comercial del proyecto y rol asignado</span></div>
            <div><b>Facturación registrada comercial</b><br><span>Horas registradas × Tarifa comercial del proyecto y rol asignado</span></div>
            <div><b>Costo real comercial</b><br><span>Horas facturables × Tarifa comercial del proyecto y rol asignado</span></div>
            <div><b>Costo real operaciones</b><br><span>Horas facturables × Tarifa operaciones del rol interno</span></div>
            <div><b>Resultado operativo</b><br><span>Costo real comercial - Costo real operaciones</span></div>
            <div><b>Progreso</b><br><span>Horas registradas / Horas estimadas</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def page_upload() -> None:
    page_header("Cargar Excel ClickUp", "")
    uploaded = st.file_uploader("Archivo Excel de ClickUp", type=["xlsx", "xlsm", "xls"], label_visibility="collapsed")
    if uploaded is None:
        st.markdown("""
        <div class="upload-empty">
            <div class="upload-icon">📤</div>
            <h3>Arrastra o selecciona el Excel de ClickUp</h3>
        </div>
        """, unsafe_allow_html=True)
        return
    try:
        raw_df, metadata = read_clickup_excel(uploaded)
        preview_df = transform_clickup_dataframe(raw_df, id_carga=0, facturable_mode="excel_or_logged")
        total_filas = len(preview_df)
        calculables = int(preview_df["es_fila_calculable"].sum())
        calc = preview_df[preview_df["es_fila_calculable"].eq(1)].copy()

        c1, c2, c3, c4 = st.columns(4)
        with c1: metric_card("Filas totales", f"{total_filas:,}")
        with c2: metric_card("Filas calculables", f"{calculables:,}")
        with c3: metric_card("Horas registradas", hours(calc["horas_registradas"].sum()))
        with c4: metric_card("Horas facturables", hours(calc["horas_facturables"].sum()))

        with st.form("guardar_excel"):
            col1, col2 = st.columns([1.5, 1])
            descripcion = col1.text_input("Descripción", placeholder="Ejemplo: Corte semanal mayo")
            usuario_carga = col2.text_input("Responsable", value="Gerencia")
            if st.form_submit_button("Guardar carga histórica", type="primary", use_container_width=True):
                id_carga = create_carga(conn, uploaded.name, descripcion, total_filas, calculables, usuario_carga)
                final_df = preview_df.copy()
                final_df["id_carga"] = id_carga
                insert_registros(conn, final_df)
                seed_catalogs_from_registros(conn, final_df)
                st.success(f"Carga guardada correctamente. ID: {id_carga}")
                st.rerun()
        with st.expander("Vista previa normalizada", expanded=True):
            show_table(calc.head(100), height=420)
    except Exception as exc:
        st.error("No se pudo procesar el Excel de ClickUp.")
        st.exception(exc)


def page_tarifas() -> None:
    page_header("Tarifas", "Tarifa operaciones por rol interno y tarifa comercial por proyecto + rol asignado.")
    roles_int = list_role_names(conn, "roles_internos") or ["Junior", "Semisenior", "Senior", "Jefe de proyecto"]
    roles_com = ROLES_FACTURABLES_FIJOS
    inicio_sugerido, fin_sugerido = default_tariff_dates()

    left, right = st.columns(2)
    with left:
        section_title("Tarifa de operaciones", "Siempre la misma por rol interno.", "$·")
        with st.form("form_tarifa_operaciones"):
            rol = st.selectbox("Rol interno", roles_int)
            tarifa = st.number_input("Tarifa operaciones/hora", min_value=0.0, step=1.0, format="%.2f")
            moneda = st.selectbox("Moneda", ["USD", "PEN"], key="ops_moneda")
            # Las fechas se manejan internamente para conservar histórico, pero no se muestran al usuario.
            fecha_inicio = inicio_sugerido
            fecha_fin = fin_sugerido
            usuario = st.text_input("Usuario", value="Gerencia", key="ops_usuario")
            obs = st.text_input("Observación", placeholder="Opcional", key="ops_obs")
            if st.form_submit_button("Guardar tarifa operaciones", type="primary", use_container_width=True):
                try:
                    upsert_tarifa_dw(conn, None, rol, tarifa, moneda, fecha_inicio, fecha_fin, usuario, obs)
                    st.success("Tarifa de operaciones guardada.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with right:
        section_title("Tarifa comercial", "Cambia por proyecto y rol asignado.", "$")
        proyectos = list_proyectos_catalogo(conn, only_active=True)
        if proyectos.empty:
            st.info("Carga primero un Excel para detectar proyectos.")
        else:
            opts = {project_label(r): r for _, r in proyectos.iterrows()}
            with st.form("form_tarifa_comercial"):
                sel = st.selectbox("Proyecto", list(opts.keys()))
                row = opts[sel]
                rol_com = st.selectbox("Rol asignado / comercial", roles_com)
                tarifa = st.number_input("Tarifa comercial/hora", min_value=0.0, step=1.0, format="%.2f")
                moneda = st.selectbox("Moneda", ["USD", "PEN"], key="com_moneda")
                # Las fechas se manejan internamente para conservar histórico, pero no se muestran al usuario.
                fecha_inicio = inicio_sugerido
                fecha_fin = fin_sugerido
                usuario = st.text_input("Usuario", value="Gerencia", key="com_usuario")
                obs = st.text_input("Observación", placeholder="Opcional", key="com_obs")
                if st.form_submit_button("Guardar tarifa comercial", type="primary", use_container_width=True):
                    try:
                        upsert_tarifa_comercial(conn, row.cliente, row.proyecto, rol_com, tarifa, moneda, fecha_inicio, fecha_fin, usuario, obs)
                        st.success("Tarifa comercial guardada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    c1, c2 = st.columns(2)
    with c1:
        section_title("Tarifas de operaciones registradas", "Histórico por rol interno.", "↧")
        show_table(_tarifas_operaciones_presentables(), height=380)
    with c2:
        section_title("Tarifas comerciales registradas", "Histórico por proyecto y rol asignado.", "↧")
        show_table(_tarifas_comerciales_presentables(), height=380)


def _gerencia_filters(page_key: str) -> tuple[int | None, pd.DataFrame | None, dict[str, Any]]:
    id_carga, carga_label = selected_carga()
    if not id_carga:
        st.warning("Primero carga un Excel activo.")
        return None, None, {}
    base_df = load_registros(conn, id_carga=id_carga, solo_calculables=True)
    if base_df.empty:
        st.warning("La carga seleccionada no tiene registros calculables.")
        return id_carga, None, {}

    f1, f2, f3, f4, f5 = st.columns([1, 1.2, 1.4, 1.5, 1.7])
    pais_sel = f1.selectbox("País", options_from(base_df, "pais"), key=f"{page_key}_pais")
    df_pais = filter_dataframe(base_df, pais=pais_sel)
    cliente_sel = f2.selectbox("Cliente", options_from(df_pais, "cliente"), key=f"{page_key}_cliente")
    df_cliente = filter_dataframe(df_pais, cliente=cliente_sel)
    proyecto_sel = f3.selectbox("Proyecto", options_from(df_cliente, "proyecto"), key=f"{page_key}_proyecto")
    df_proy = filter_dataframe(df_cliente, proyecto=proyecto_sel)
    hito_sel = f4.selectbox("Hito facturable", options_from(df_proy, "hito_facturable"), key=f"{page_key}_hito")
    df_hito = filter_dataframe(df_proy, hito=hito_sel)
    min_f, max_f = date_range_from(df_hito)
    with f5:
        fecha_inicio, fecha_fin = st.date_input("Fecha inicio / fin", value=(min_f, max_f), min_value=min_f, max_value=max_f, key=f"{page_key}_fecha")

    filtered = filter_dataframe(base_df, pais_sel, cliente_sel, proyecto_sel, hito_sel, fecha_inicio, fecha_fin)
    filtros = {
        "id_carga": id_carga, "archivo": carga_label, "pais": pais_sel, "cliente": cliente_sel,
        "proyecto": proyecto_sel, "hito_facturable": hito_sel, "fecha_inicio": fecha_inicio.isoformat(), "fecha_fin": fecha_fin.isoformat(),
    }
    return id_carga, filtered, filtros


def _show_tariff_alerts_bottom(enriched: pd.DataFrame) -> pd.DataFrame:
    alertas = enriched[enriched["alerta_tarifa"].fillna("").astype(str).str.strip() != ""] if not enriched.empty else pd.DataFrame()
    if not alertas.empty:
        with st.expander(f"Control de tarifas pendientes ({len(alertas):,} registros)", expanded=False):
            st.caption("Estos registros calculan en cero la tarifa que falta. Registra tarifa de operaciones por rol o tarifa comercial por proyecto y rol.")
            cols = ["pais", "cliente", "proyecto", "hito_facturable", "assignee", "rol_estimado", "rol_asignado", "fecha_referencia", "alerta_tarifa"]
            show_table(alertas[[c for c in cols if c in alertas.columns]], height=300)
    return alertas


def _show_progress(enriched: pd.DataFrame, mode: str = "general") -> None:
    section_title("Progreso por proyecto", "Progreso = Horas registradas / Horas estimadas.", "▰")
    prog = project_progress(enriched)
    if prog.empty:
        st.info("No hay datos para calcular progreso.")
        return
    for _, row in prog.iterrows():
        avance = float(row["avance_horas"] or 0)
        width = min(max(avance * 100, 0), 100)
        if mode == "servicios":
            money_label = "Costo operaciones"
            money_value = float(row.get("costo_real_operaciones", 0) or 0)
            kind = ""
        else:
            money_label = "Resultado operativo"
            money_value = float(row.get("margen_real", 0) or 0)
            kind = "good" if money_value >= 0 else "bad"
        st.markdown(f"""
        <div class="progress-card">
            <div class="progress-title"><div class="progress-name">{row['pais']} · {row['cliente']} · {row['proyecto']}</div><div class="progress-pct">{avance*100:,.1f}%</div></div>
            <div class="track"><div class="bar" style="width:{width:.1f}%"></div></div>
            <div class="progress-meta"><span>{row['horas_registradas']:,.2f} h registradas de {row['horas_estimadas']:,.2f} h estimadas</span><span class="{kind}">{money_label}: {money(money_value)}</span></div>
        </div>
        """, unsafe_allow_html=True)


def _show_final_charts(enriched: pd.DataFrame, suffix: str = "", include_cost_commercial: bool = True) -> None:
    section_title("Gráficos finales", "Comparativos visuales de horas y montos.", "↗")
    if enriched.empty:
        st.info("No hay datos para graficar.")
        return
    rol_chart = enriched.groupby("rol_asignado", dropna=False).agg(
        **{"Horas estimadas": ("horas_estimadas", "sum"), "Horas registradas": ("horas_registradas", "sum")}
    ).reset_index().melt(id_vars="rol_asignado", var_name="Tipo", value_name="Horas")
    fig1 = px.bar(rol_chart, x="rol_asignado", y="Horas", color="Tipo", barmode="group", title=f"Duración estimada vs registrada por rol {suffix}")
    fig1.update_layout(plot_bgcolor="white", paper_bgcolor="white", font_family="Inter", title_font_size=18, legend_title_text="", xaxis_title="Rol asignado")
    st.plotly_chart(fig1, use_container_width=True)

    if include_cost_commercial:
        proy_chart = enriched.groupby("proyecto", dropna=False).agg(
            **{"Facturación estimada comercial": ("facturacion_estimada", "sum"), "Costo real comercial": ("costo_real_comercial", "sum")}
        ).reset_index().melt(id_vars="proyecto", var_name="Tipo", value_name="Monto")
        title = f"Facturación estimada comercial vs costo real comercial por proyecto {suffix}"
    else:
        proy_chart = enriched.groupby("proyecto", dropna=False).agg(
            **{"Facturación estimada operaciones": ("facturacion_estimada_operaciones", "sum"), "Facturación registrada operaciones": ("facturacion_registrada_operaciones", "sum"), "Costo operaciones": ("costo_real_operaciones", "sum")}
        ).reset_index().melt(id_vars="proyecto", var_name="Tipo", value_name="Monto")
        title = f"Montos de operaciones por proyecto {suffix}"
    fig2 = px.bar(proy_chart, x="proyecto", y="Monto", color="Tipo", barmode="group", title=title)
    fig2.update_layout(plot_bgcolor="white", paper_bgcolor="white", font_family="Inter", title_font_size=18, legend_title_text="")
    st.plotly_chart(fig2, use_container_width=True)


def _enriched(page_key: str) -> tuple[int | None, pd.DataFrame | None, dict[str, Any]]:
    id_carga, filtered, filtros = _gerencia_filters(page_key)
    if filtered is None:
        return id_carga, None, filtros
    enriched = apply_tariffs(filtered, load_tarifas_dw(conn), load_tarifas_comerciales(conn), commercial_basis="proyecto_rol")
    return id_carga, enriched, filtros


def page_gerencia_general() -> None:
    page_header("Gerencia General", "KPIs ejecutivos de horas, facturación, costos y resultado operativo.")
    id_carga, enriched, filtros = _enriched("general")
    if enriched is None:
        return
    metrics = total_metrics(enriched)

    section_title("KPIs de horas", "Primero se revisa consumo y avance operativo.", "h")
    h1, h2, h3, h4 = st.columns(4)
    with h1: metric_card("Horas estimadas", hours(metrics["total_estimado"]), "Planificadas")
    with h2: metric_card("Horas registradas", hours(metrics["total_registrado"]), "Consumidas")
    with h3: metric_card("Horas facturables", hours(metrics["facturable_real_horas"]), "Base comercial")
    with h4: metric_card("Progreso", pct(metrics["progreso"]), "Registradas / estimadas")

    _show_progress(enriched, mode="general")

    section_title("KPIs de dinero", "Luego se revisa facturación comercial, costos y resultado operativo.", "$")
    d1, d2, d3 = st.columns(3)
    with d1: metric_card("Facturación estimada comercial", money(metrics["facturacion_estimada"]), "Horas estimadas × tarifa comercial")
    with d2: metric_card("Facturación registrada comercial", money(metrics["facturacion_registrada"]), "Horas registradas × tarifa comercial")
    with d3: metric_card("Costo real comercial", money(metrics["costo_real_comercial"]), "Horas facturables × tarifa comercial")
    d4, d5 = st.columns(2)
    with d4: metric_card("Costo real operaciones", money(metrics["costo_real_operaciones"]), "Horas facturables × tarifa operaciones")
    with d5: metric_card("Resultado operativo", money(metrics["resultado_operativo"]), f"{pct(metrics['margen_pct'])}", "good" if metrics["resultado_operativo"] >= 0 else "bad")
    resumen = build_summary(enriched, mode="general")
    detalle = build_detail(enriched, mode="general")
    section_title("Resumen por país y proyecto", "El proyecto suma todos los roles y personas del proyecto.", "Σ")
    show_table(resumen, height=360)
    section_title("Detalle por persona y rol", "Aquí se observa la tarifa de operaciones del rol y la tarifa comercial del proyecto/rol asignado.", "☷")
    show_table(detalle, height=430)
    alertas = _show_tariff_alerts_bottom(enriched)
    excel_bytes = dataframe_to_excel_bytes(resumen=present_df(resumen), detalle=present_df(detalle), datos_filtrados=present_df(enriched), filtros=filtros, alertas_tarifa=present_df(alertas) if not alertas.empty else alertas)
    st.download_button("Descargar reporte Gerencia General", data=excel_bytes, file_name=f"reporte_gerencia_general_carga_{id_carga}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
    _show_final_charts(enriched, "— general")


def page_gerencia_servicios() -> None:
    page_header("Gerencia de Servicios", "Vista de servicios: horas y costo de operaciones.")
    id_carga, enriched, filtros = _enriched("servicios")
    if enriched is None:
        return
    metrics = total_metrics(enriched)

    st.markdown("### Horas")
    h1, h2, h3, h4 = st.columns(4)
    with h1: metric_card("Horas estimadas", hours(metrics["total_estimado"]), "Plan operativo")
    with h2: metric_card("Horas registradas", hours(metrics["total_registrado"]), "Consumo real")
    with h3: metric_card("Horas facturables", hours(metrics["facturable_real_horas"]), "Base comercial")
    with h4: metric_card("Progreso", pct(metrics["progreso"]), "Registradas / estimadas")

    st.markdown("### Operación")
    d1, d2, d3 = st.columns(3)
    with d1: metric_card("Facturación estimada operaciones", money(metrics["facturacion_estimada_operaciones"]), "Horas estimadas × tarifa operaciones")
    with d2: metric_card("Facturación registrada operaciones", money(metrics["facturacion_registrada_operaciones"]), "Horas registradas × tarifa operaciones")
    with d3: metric_card("Costo Operaciones", money(metrics["costo_real_operaciones"]), "Horas facturables × tarifa operaciones")

    _show_progress(enriched, mode="servicios")
    resumen = build_summary(enriched, mode="servicios")
    detalle = build_detail(enriched, mode="servicios")
    section_title("Resumen por país y proyecto", "País, proyecto, horas y montos de operaciones.", "Σ")
    show_table(resumen, height=340)
    section_title("Detalle por persona y rol", "Se omite tarifa comercial/hora; se muestra la tarifa de operaciones aplicada al rol interno.", "☷")
    show_table(detalle, height=430)
    alertas = _show_tariff_alerts_bottom(enriched)
    excel_bytes = dataframe_to_excel_bytes(resumen=present_df(resumen), detalle=present_df(detalle), datos_filtrados=present_df(enriched), filtros=filtros, alertas_tarifa=present_df(alertas) if not alertas.empty else alertas)
    st.download_button("Descargar reporte Gerencia de Servicios", data=excel_bytes, file_name=f"reporte_gerencia_servicios_carga_{id_carga}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
    _show_final_charts(enriched, "— servicios", include_cost_commercial=False)


def page_history() -> None:
    page_header("Histórico de cargas", "Activa o inactiva archivos cargados.")
    cargas = list_cargas(conn)
    show_table(cargas, height=360)
    if not cargas.empty:
        opts = {f"{int(r.id_carga)} | {r.nombre_archivo} | {r.estado}": int(r.id_carga) for _, r in cargas.iterrows()}
        sel = st.selectbox("Carga", list(opts.keys()))
        c1, c2 = st.columns(2)
        if c1.button("Marcar ACTIVA", use_container_width=True):
            set_carga_estado(conn, opts[sel], "ACTIVA")
            st.rerun()
        if c2.button("Marcar INACTIVA", use_container_width=True):
            set_carga_estado(conn, opts[sel], "INACTIVA")
            st.rerun()

# -----------------------------------------------------------------------------
# Menú
# -----------------------------------------------------------------------------
st.sidebar.markdown("""
<div class="brand-card"><div class="brand-row"><div class="brand-logo">DW</div><div><div class="brand-title">DW Manager</div><div class="brand-subtitle">Horas · tarifas · resultado operativo</div></div></div><div class="brand-pill">☰ Menú principal</div></div>
""", unsafe_allow_html=True)
page = st.sidebar.radio(
    "Menú principal",
    [
        "🏠 Inicio",
        "📤 Cargar Excel ClickUp",
        "💵 Tarifas",
        "📊 Gerencia General",
        "🧭 Gerencia de Servicios",
        "🗂 Histórico de cargas",
    ],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
st.sidebar.caption("Base SQLite local")
st.sidebar.code(str(DB_PATH))

if page.endswith("Inicio"):
    page_inicio()
elif page.endswith("Cargar Excel ClickUp"):
    page_upload()
elif page.endswith("Tarifas"):
    page_tarifas()
elif page.endswith("Gerencia General"):
    page_gerencia_general()
elif page.endswith("Gerencia de Servicios"):
    page_gerencia_servicios()
elif page.endswith("Histórico de cargas"):
    page_history()

st.markdown('<div class="app-footer">v21 · lógica actualizada · costo operaciones por horas facturables</div>', unsafe_allow_html=True)
