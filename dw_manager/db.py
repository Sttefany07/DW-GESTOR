from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

DB_DEFAULT_PATH = Path("data") / "dw_clickup.sqlite3"
HITO_NO_APLICA = "No aplica"
ROLES_FACTURABLES_FIJOS = ["Jefe de proyecto", "Senior", "Semisenior", "Junior"]


def normalize_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def canonicalize_facturable_role(value: object) -> str:
    key = normalize_key(value)
    aliases = {
        "jefe de proyecto": "Jefe de proyecto",
        "jefe proyecto": "Jefe de proyecto",
        "jefe proyect": "Jefe de proyecto",
        "jefe de proyect": "Jefe de proyecto",
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


def normalize_hito(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if not text or normalize_key(text) in {"empty", "sin hito", "no aplica", "n/a", "na", "nan", "none", "null", "-"}:
        return HITO_NO_APLICA
    return text


def get_connection(db_path: str | Path = DB_DEFAULT_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cargas_excel (
            id_carga INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_archivo TEXT NOT NULL,
            descripcion TEXT,
            fecha_carga TEXT NOT NULL,
            total_filas INTEGER DEFAULT 0,
            filas_calculables INTEGER DEFAULT 0,
            usuario_carga TEXT,
            estado TEXT NOT NULL DEFAULT 'ACTIVA'
        );

        CREATE TABLE IF NOT EXISTS registros_clickup (
            id_registro INTEGER PRIMARY KEY AUTOINCREMENT,
            id_carga INTEGER NOT NULL,
            task_id TEXT,
            task_name TEXT,
            parent_id TEXT,
            parent_name TEXT,
            assignee TEXT,
            fecha_referencia TEXT,
            pais TEXT,
            cliente TEXT,
            proyecto TEXT,
            hito_facturable TEXT,
            rol TEXT,
            rol_facturable TEXT,
            status TEXT,
            task_type TEXT,
            horas_estimadas REAL DEFAULT 0,
            horas_registradas REAL DEFAULT 0,
            horas_facturables REAL DEFAULT 0,
            fuente_horas_facturables TEXT,
            es_fila_calculable INTEGER DEFAULT 1,
            regla_limpieza TEXT,
            alerta_datos TEXT,
            raw_json TEXT,
            FOREIGN KEY(id_carga) REFERENCES cargas_excel(id_carga) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_registros_carga ON registros_clickup(id_carga);
        CREATE INDEX IF NOT EXISTS idx_registros_filtros ON registros_clickup(pais, cliente, proyecto, hito_facturable, fecha_referencia);
        CREATE INDEX IF NOT EXISTS idx_registros_persona ON registros_clickup(assignee, rol, rol_facturable);

        CREATE TABLE IF NOT EXISTS roles_internos (
            id_rol_interno INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nombre_normalizado TEXT NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS roles_facturables (
            id_rol_facturable INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nombre_normalizado TEXT NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS consultores (
            id_consultor INTEGER PRIMARY KEY AUTOINCREMENT,
            nombres TEXT NOT NULL,
            nombre_normalizado TEXT NOT NULL UNIQUE,
            email TEXT UNIQUE,
            rol_principal TEXT,
            rol_facturable TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL,
            usuario_registro TEXT,
            observacion TEXT
        );

        CREATE TABLE IF NOT EXISTS catalogo_proyectos (
            id_proyecto_catalogo INTEGER PRIMARY KEY AUTOINCREMENT,
            pais TEXT NOT NULL,
            cliente TEXT NOT NULL,
            proyecto TEXT NOT NULL,
            pais_norm TEXT NOT NULL,
            cliente_norm TEXT NOT NULL,
            proyecto_norm TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_inicio TEXT,
            fecha_fin TEXT,
            fecha_registro TEXT NOT NULL,
            UNIQUE(pais_norm, cliente_norm, proyecto_norm)
        );

        CREATE TABLE IF NOT EXISTS catalogo_hitos (
            id_hito_catalogo INTEGER PRIMARY KEY AUTOINCREMENT,
            id_proyecto_catalogo INTEGER NOT NULL,
            hito_facturable TEXT NOT NULL,
            hito_norm TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_inicio TEXT,
            fecha_fin TEXT,
            fecha_registro TEXT NOT NULL,
            FOREIGN KEY(id_proyecto_catalogo) REFERENCES catalogo_proyectos(id_proyecto_catalogo) ON DELETE CASCADE,
            UNIQUE(id_proyecto_catalogo, hito_norm)
        );

        CREATE TABLE IF NOT EXISTS asignaciones_consultor (
            id_asignacion INTEGER PRIMARY KEY AUTOINCREMENT,
            id_consultor INTEGER NOT NULL,
            id_proyecto_catalogo INTEGER NOT NULL,
            id_hito_catalogo INTEGER,
            rol_interno TEXT NOT NULL,
            rol_facturable TEXT NOT NULL,
            fecha_inicio TEXT NOT NULL,
            fecha_fin TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL,
            usuario_registro TEXT,
            observacion TEXT,
            FOREIGN KEY(id_consultor) REFERENCES consultores(id_consultor),
            FOREIGN KEY(id_proyecto_catalogo) REFERENCES catalogo_proyectos(id_proyecto_catalogo),
            FOREIGN KEY(id_hito_catalogo) REFERENCES catalogo_hitos(id_hito_catalogo),
            UNIQUE(id_consultor, id_proyecto_catalogo, id_hito_catalogo, rol_interno, rol_facturable, fecha_inicio)
        );

        CREATE TABLE IF NOT EXISTS tarifas_dw_historico (
            id_tarifa_dw INTEGER PRIMARY KEY AUTOINCREMENT,
            persona TEXT NOT NULL,
            rol_interno TEXT NOT NULL,
            tarifa_real_dw_hora REAL NOT NULL,
            moneda TEXT NOT NULL DEFAULT 'USD',
            fecha_inicio_vigencia TEXT NOT NULL,
            fecha_fin_vigencia TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'VIGENTE',
            usuario_registro TEXT,
            fecha_registro TEXT NOT NULL,
            observacion TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tarifa_dw_lookup ON tarifas_dw_historico(persona, rol_interno, fecha_inicio_vigencia, fecha_fin_vigencia);

        CREATE TABLE IF NOT EXISTS tarifas_comerciales_historico (
            id_tarifa_comercial INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL DEFAULT '',
            proyecto TEXT NOT NULL DEFAULT '',
            persona TEXT NOT NULL DEFAULT 'PROYECTO_ROL',
            rol_facturable TEXT NOT NULL DEFAULT '',
            tarifa_comercial_hora REAL NOT NULL,
            moneda TEXT NOT NULL DEFAULT 'USD',
            fecha_inicio_vigencia TEXT NOT NULL,
            fecha_fin_vigencia TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'VIGENTE',
            usuario_registro TEXT,
            fecha_registro TEXT NOT NULL,
            observacion TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tarifa_comercial_lookup ON tarifas_comerciales_historico(proyecto, rol_facturable, fecha_inicio_vigencia, fecha_fin_vigencia);
        """
    )
    _migrate_existing_db(conn)
    for rol in ROLES_FACTURABLES_FIJOS:
        conn.execute(
            "INSERT OR IGNORE INTO roles_facturables(nombre, nombre_normalizado, activo, fecha_registro) VALUES (?, ?, 1, ?)",
            (rol, normalize_key(rol), _today_str()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO roles_internos(nombre, nombre_normalizado, activo, fecha_registro) VALUES (?, ?, 1, ?)",
            (rol, normalize_key(rol), _today_str()),
        )
    conn.commit()


def _migrate_existing_db(conn: sqlite3.Connection) -> None:
    def cols(table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for table_name in ["registros_clickup"]:
        existing = cols(table_name)
        for col, ddl in {"fuente_horas_facturables": "TEXT", "alerta_datos": "TEXT"}.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {ddl}")
    existing = cols("consultores")
    if "rol_facturable" not in existing:
        conn.execute("ALTER TABLE consultores ADD COLUMN rol_facturable TEXT")
    for table_name in ["catalogo_proyectos", "catalogo_hitos"]:
        existing = cols(table_name)
        for col in ["fecha_inicio", "fecha_fin"]:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} TEXT")
    existing = cols("tarifas_comerciales_historico")
    if "persona" not in existing:
        conn.execute("ALTER TABLE tarifas_comerciales_historico ADD COLUMN persona TEXT DEFAULT 'PROYECTO_ROL'")
    if "cliente" not in existing:
        conn.execute("ALTER TABLE tarifas_comerciales_historico ADD COLUMN cliente TEXT DEFAULT ''")
    if "proyecto" not in existing:
        conn.execute("ALTER TABLE tarifas_comerciales_historico ADD COLUMN proyecto TEXT DEFAULT ''")
    if "rol_facturable" not in existing:
        conn.execute("ALTER TABLE tarifas_comerciales_historico ADD COLUMN rol_facturable TEXT DEFAULT ''")


# -----------------------------------------------------------------------------
# Cargas ClickUp
# -----------------------------------------------------------------------------

def create_carga(conn: sqlite3.Connection, nombre_archivo: str, descripcion: str | None, total_filas: int, filas_calculables: int, usuario_carga: str | None = None) -> int:
    cur = conn.execute(
        """
        INSERT INTO cargas_excel(nombre_archivo, descripcion, fecha_carga, total_filas, filas_calculables, usuario_carga)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (nombre_archivo, descripcion, _today_str(), total_filas, filas_calculables, usuario_carga),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_registros(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    expected = [
        "id_carga", "task_id", "task_name", "parent_id", "parent_name", "assignee", "fecha_referencia",
        "pais", "cliente", "proyecto", "hito_facturable", "rol", "rol_facturable", "status", "task_type",
        "horas_estimadas", "horas_registradas", "horas_facturables", "fuente_horas_facturables",
        "es_fila_calculable", "regla_limpieza", "alerta_datos", "raw_json",
    ]
    for col in expected:
        if col not in df.columns:
            df[col] = None
    df[expected].to_sql("registros_clickup", conn, if_exists="append", index=False)
    conn.commit()


def list_cargas(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT id_carga, nombre_archivo, descripcion, fecha_carga, total_filas, filas_calculables, usuario_carga, estado
        FROM cargas_excel
        ORDER BY id_carga DESC
        """,
        conn,
    )


def get_latest_carga_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT id_carga FROM cargas_excel WHERE estado = 'ACTIVA' ORDER BY id_carga DESC LIMIT 1").fetchone()
    return int(row[0]) if row else None


def load_registros(conn: sqlite3.Connection, id_carga: Optional[int] = None, solo_calculables: bool = True) -> pd.DataFrame:
    where, params = [], []
    if id_carga is not None:
        where.append("id_carga = ?")
        params.append(id_carga)
    if solo_calculables:
        where.append("es_fila_calculable = 1")
    sql = "SELECT * FROM registros_clickup"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return pd.read_sql_query(sql, conn, params=params)


def set_carga_estado(conn: sqlite3.Connection, id_carga: int, estado: str) -> None:
    conn.execute("UPDATE cargas_excel SET estado = ? WHERE id_carga = ?", (estado, id_carga))
    conn.commit()


# -----------------------------------------------------------------------------
# Roles y consultores
# -----------------------------------------------------------------------------

def add_role(conn: sqlite3.Connection, table: str, nombre: str) -> None:
    nombre = (nombre or "").strip()
    if not nombre:
        return
    if table not in {"roles_internos", "roles_facturables"}:
        raise ValueError("Tabla de rol no permitida")
    if table == "roles_facturables":
        nombre = canonicalize_facturable_role(nombre)
        if not nombre:
            return
    conn.execute(
        f"INSERT OR IGNORE INTO {table}(nombre, nombre_normalizado, activo, fecha_registro) VALUES (?, ?, 1, ?)",
        (nombre, normalize_key(nombre), _today_str()),
    )
    conn.commit()


def list_roles(conn: sqlite3.Connection, table: str, only_active: bool = True) -> pd.DataFrame:
    if table not in {"roles_internos", "roles_facturables"}:
        raise ValueError("Tabla de rol no permitida")
    if table == "roles_facturables":
        placeholders = ",".join("?" for _ in ROLES_FACTURABLES_FIJOS)
        sql = f"SELECT * FROM roles_facturables WHERE nombre IN ({placeholders})"
        params = ROLES_FACTURABLES_FIJOS
        if only_active:
            sql += " AND activo = 1"
        df = pd.read_sql_query(sql, conn, params=params)
        if not df.empty:
            order = {name: i for i, name in enumerate(ROLES_FACTURABLES_FIJOS)}
            df["_orden"] = df["nombre"].map(order).fillna(99)
            df = df.sort_values("_orden").drop(columns=["_orden"])
        return df
    sql = f"SELECT * FROM {table}"
    if only_active:
        sql += " WHERE activo = 1"
    sql += " ORDER BY nombre"
    return pd.read_sql_query(sql, conn)


def list_role_names(conn: sqlite3.Connection, table: str, include_blank: bool = False) -> list[str]:
    vals = ROLES_FACTURABLES_FIJOS.copy() if table == "roles_facturables" else list_roles(conn, table, True)["nombre"].astype(str).tolist()
    return ([""] if include_blank else []) + vals


def create_consultor(
    conn: sqlite3.Connection,
    nombres: str,
    email: str | None = None,
    rol_principal: str | None = None,
    rol_facturable: str | None = None,
    usuario_registro: str | None = None,
    observacion: str | None = None,
) -> tuple[bool, str]:
    nombres = (nombres or "").strip()
    email = (email or "").strip().lower() or None
    rol_principal = (rol_principal or "").strip()
    rol_facturable = canonicalize_facturable_role(rol_facturable or "")
    if not nombres:
        return False, "El nombre del consultor es obligatorio."
    key = normalize_key(nombres)
    row = conn.execute("SELECT nombres FROM consultores WHERE nombre_normalizado = ?", (key,)).fetchone()
    if row:
        return False, f"Ya existe un consultor registrado con ese nombre: {row['nombres']}."
    if email:
        row = conn.execute("SELECT nombres FROM consultores WHERE lower(email) = lower(?)", (email,)).fetchone()
        if row:
            return False, f"Ya existe un consultor con ese email: {row['nombres']}."
    conn.execute(
        """
        INSERT INTO consultores(nombres, nombre_normalizado, email, rol_principal, rol_facturable, activo, fecha_registro, usuario_registro, observacion)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (nombres, key, email, rol_principal, rol_facturable, _today_str(), usuario_registro, observacion),
    )
    conn.commit()
    return True, "Consultor registrado correctamente."


def upsert_consultor_from_name(conn: sqlite3.Connection, nombres: str, rol_principal: str | None = None, rol_facturable: str | None = None) -> None:
    nombres = (nombres or "").strip()
    if not nombres:
        return
    key = normalize_key(nombres)
    rol_facturable = canonicalize_facturable_role(rol_facturable or "")
    conn.execute(
        """
        INSERT OR IGNORE INTO consultores(nombres, nombre_normalizado, email, rol_principal, rol_facturable, activo, fecha_registro, usuario_registro, observacion)
        VALUES (?, ?, NULL, ?, ?, 1, ?, 'carga_excel', 'Detectado desde archivo ClickUp')
        """,
        (nombres, key, (rol_principal or "").strip(), rol_facturable, _today_str()),
    )
    conn.execute(
        """
        UPDATE consultores
        SET rol_principal = CASE WHEN COALESCE(TRIM(rol_principal), '') = '' THEN ? ELSE rol_principal END,
            rol_facturable = CASE WHEN COALESCE(TRIM(rol_facturable), '') = '' THEN ? ELSE rol_facturable END
        WHERE nombre_normalizado = ?
        """,
        ((rol_principal or "").strip(), rol_facturable, key),
    )
    conn.commit()


def list_consultores(conn: sqlite3.Connection, only_active: bool = True) -> pd.DataFrame:
    sql = "SELECT id_consultor, nombres, email, rol_principal, rol_facturable, activo, fecha_registro, usuario_registro, observacion FROM consultores"
    if only_active:
        sql += " WHERE activo = 1"
    sql += " ORDER BY nombres"
    return pd.read_sql_query(sql, conn)


def set_consultor_estado(conn: sqlite3.Connection, id_consultor: int, activo: bool) -> None:
    conn.execute("UPDATE consultores SET activo = ? WHERE id_consultor = ?", (1 if activo else 0, id_consultor))
    conn.commit()


def update_consultor_rol(
    conn: sqlite3.Connection,
    id_consultor: int,
    rol_principal: str,
    usuario_registro: str | None = None,
    observacion: str | None = None,
    rol_facturable: str | None = None,
) -> tuple[bool, str]:
    rol_principal = (rol_principal or "").strip()
    rol_facturable = canonicalize_facturable_role(rol_facturable or "")
    if not rol_principal:
        return False, "El rol interno es obligatorio."
    row = conn.execute("SELECT nombres FROM consultores WHERE id_consultor = ?", (id_consultor,)).fetchone()
    if not row:
        return False, "No se encontró el consultor seleccionado."
    conn.execute(
        """
        UPDATE consultores
        SET rol_principal = ?,
            rol_facturable = CASE WHEN COALESCE(TRIM(?), '') = '' THEN rol_facturable ELSE ? END,
            usuario_registro = COALESCE(?, usuario_registro),
            observacion = CASE
                WHEN COALESCE(TRIM(?), '') = '' THEN observacion
                WHEN COALESCE(TRIM(observacion), '') = '' THEN ?
                ELSE observacion || ' | ' || ?
            END
        WHERE id_consultor = ?
        """,
        (rol_principal, rol_facturable, rol_facturable, usuario_registro, observacion, observacion, observacion, id_consultor),
    )
    conn.commit()
    return True, f"Rol actualizado para {row['nombres']}."


# -----------------------------------------------------------------------------
# Catálogos de proyectos / hitos desde ClickUp
# -----------------------------------------------------------------------------

def upsert_proyecto(conn: sqlite3.Connection, pais: str, cliente: str, proyecto: str) -> Optional[int]:
    pais, cliente, proyecto = (pais or "").strip(), (cliente or "").strip(), (proyecto or "").strip()
    if not pais or not cliente or not proyecto:
        return None
    keys = (normalize_key(pais), normalize_key(cliente), normalize_key(proyecto))
    conn.execute(
        """
        INSERT OR IGNORE INTO catalogo_proyectos(pais, cliente, proyecto, pais_norm, cliente_norm, proyecto_norm, activo, fecha_registro)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (pais, cliente, proyecto, *keys, _today_str()),
    )
    row = conn.execute(
        "SELECT id_proyecto_catalogo FROM catalogo_proyectos WHERE pais_norm=? AND cliente_norm=? AND proyecto_norm=?",
        keys,
    ).fetchone()
    conn.commit()
    return int(row[0]) if row else None


def upsert_hito(conn: sqlite3.Connection, id_proyecto_catalogo: int, hito_facturable: str) -> Optional[int]:
    hito = normalize_hito(hito_facturable)
    conn.execute(
        """
        INSERT OR IGNORE INTO catalogo_hitos(id_proyecto_catalogo, hito_facturable, hito_norm, activo, fecha_registro)
        VALUES (?, ?, ?, 1, ?)
        """,
        (id_proyecto_catalogo, hito, normalize_key(hito), _today_str()),
    )
    row = conn.execute(
        "SELECT id_hito_catalogo FROM catalogo_hitos WHERE id_proyecto_catalogo=? AND hito_norm=?",
        (id_proyecto_catalogo, normalize_key(hito)),
    ).fetchone()
    conn.commit()
    return int(row[0]) if row else None


def list_proyectos_catalogo(conn: sqlite3.Connection, only_active: bool = True) -> pd.DataFrame:
    sql = "SELECT id_proyecto_catalogo, pais, cliente, proyecto, fecha_inicio, fecha_fin, activo, fecha_registro FROM catalogo_proyectos"
    if only_active:
        sql += " WHERE activo = 1"
    sql += " ORDER BY pais, cliente, proyecto"
    return pd.read_sql_query(sql, conn)


def list_hitos_catalogo(conn: sqlite3.Connection, id_proyecto_catalogo: int | None = None, only_active: bool = True) -> pd.DataFrame:
    sql = """
        SELECT h.id_hito_catalogo, h.id_proyecto_catalogo, p.pais, p.cliente, p.proyecto,
               h.hito_facturable, h.fecha_inicio, h.fecha_fin, h.activo, h.fecha_registro
        FROM catalogo_hitos h
        JOIN catalogo_proyectos p ON p.id_proyecto_catalogo = h.id_proyecto_catalogo
    """
    where, params = [], []
    if id_proyecto_catalogo is not None:
        where.append("h.id_proyecto_catalogo = ?")
        params.append(id_proyecto_catalogo)
    if only_active:
        where.append("h.activo = 1")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.pais, p.cliente, p.proyecto, h.hito_facturable"
    return pd.read_sql_query(sql, conn, params=params)


def create_asignacion(
    conn: sqlite3.Connection,
    id_consultor: int,
    id_proyecto_catalogo: int,
    id_hito_catalogo: int | None,
    rol_interno: str,
    rol_facturable: str,
    fecha_inicio: date,
    fecha_fin: date | None,
    usuario_registro: str | None = None,
    observacion: str | None = None,
) -> tuple[bool, str]:
    rol_interno = (rol_interno or "").strip()
    rol_facturable = canonicalize_facturable_role(rol_facturable)
    if not rol_interno or not rol_facturable:
        return False, "Rol interno y rol facturable son obligatorios."
    if fecha_fin is None:
        return False, "La fecha fin es obligatoria."
    if fecha_fin < fecha_inicio:
        return False, "La fecha fin no puede ser menor que la fecha inicio."
    try:
        conn.execute(
            """
            INSERT INTO asignaciones_consultor(id_consultor, id_proyecto_catalogo, id_hito_catalogo, rol_interno, rol_facturable, fecha_inicio, fecha_fin, activo, fecha_registro, usuario_registro, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (id_consultor, id_proyecto_catalogo, id_hito_catalogo, rol_interno, rol_facturable, fecha_inicio.isoformat(), fecha_fin.isoformat(), _today_str(), usuario_registro, observacion),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return False, "La asignación ya existe con la misma combinación."
    return True, "Asignación registrada correctamente."


def list_asignaciones(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT a.id_asignacion, c.nombres AS consultor, p.pais, p.cliente, p.proyecto,
               COALESCE(h.hito_facturable, 'Todo el proyecto') AS hito_facturable,
               a.rol_interno, a.rol_facturable, a.fecha_inicio, a.fecha_fin,
               CASE WHEN a.activo=1 THEN 'ACTIVA' ELSE 'INACTIVA' END AS estado,
               a.usuario_registro, a.observacion
        FROM asignaciones_consultor a
        JOIN consultores c ON c.id_consultor = a.id_consultor
        JOIN catalogo_proyectos p ON p.id_proyecto_catalogo = a.id_proyecto_catalogo
        LEFT JOIN catalogo_hitos h ON h.id_hito_catalogo = a.id_hito_catalogo
        ORDER BY p.pais, p.cliente, p.proyecto, c.nombres
        """,
        conn,
    )


def seed_catalogs_from_registros(conn: sqlite3.Connection, df: pd.DataFrame) -> dict[str, int]:
    counts = {"consultores": 0, "roles_internos": 0, "roles_facturables": 0, "proyectos": 0, "hitos": 0}
    if df.empty:
        return counts
    before_total = conn.total_changes
    for rol in sorted(set(str(x).strip() for x in df.get("rol", pd.Series(dtype=str)).dropna() if str(x).strip())):
        add_role(conn, "roles_internos", rol)
    counts["roles_internos"] = conn.total_changes - before_total
    before_total = conn.total_changes
    for rol in sorted(set(str(x).strip() for x in df.get("rol_facturable", pd.Series(dtype=str)).dropna() if str(x).strip())):
        add_role(conn, "roles_facturables", rol)
    counts["roles_facturables"] = conn.total_changes - before_total

    before_total = conn.total_changes
    cols = [c for c in ["assignee", "rol", "rol_facturable"] if c in df.columns]
    if cols:
        for _, row in df[cols].drop_duplicates().iterrows():
            upsert_consultor_from_name(conn, str(row.get("assignee", "")).strip(), str(row.get("rol", "")).strip(), str(row.get("rol_facturable", "")).strip())
    counts["consultores"] = conn.total_changes - before_total

    before_total = conn.total_changes
    if all(c in df.columns for c in ["pais", "cliente", "proyecto"]):
        cols = ["pais", "cliente", "proyecto"] + (["hito_facturable"] if "hito_facturable" in df.columns else [])
        for _, row in df[cols].drop_duplicates().iterrows():
            pid = upsert_proyecto(conn, str(row.get("pais", "")).strip(), str(row.get("cliente", "")).strip(), str(row.get("proyecto", "")).strip())
            if pid:
                upsert_hito(conn, pid, row.get("hito_facturable", ""))
    # Separar conteos aproximados por consulta final
    counts["proyectos"] = len(list_proyectos_catalogo(conn, only_active=False))
    counts["hitos"] = len(list_hitos_catalogo(conn, only_active=False))
    return counts


# -----------------------------------------------------------------------------
# Tarifas históricas de operaciones y comerciales
# -----------------------------------------------------------------------------

def _close_previous_tariff(conn: sqlite3.Connection, table: str, key_columns: list[str], key_values: list[object], start_date: date) -> None:
    fin_previo = (start_date - timedelta(days=1)).isoformat()
    conditions, params = [], []
    for col, value in zip(key_columns, key_values):
        conditions.append(f"TRIM(COALESCE({col}, '')) = TRIM(?)")
        params.append(str(value or "").strip())
    conditions.append("estado = 'VIGENTE'")
    conditions.append("date(fecha_inicio_vigencia) <= date(?)")
    params.append(start_date.isoformat())
    sql = f"""
        UPDATE {table}
        SET fecha_fin_vigencia = ?, estado = 'HISTORICA'
        WHERE {' AND '.join(conditions)}
          AND date(fecha_fin_vigencia) >= date(?)
    """
    conn.execute(sql, [fin_previo] + params + [start_date.isoformat()])


def upsert_tarifa_dw(conn: sqlite3.Connection, persona: str | None, rol_interno: str, tarifa_real_dw_hora: float, moneda: str, fecha_inicio_vigencia: date, fecha_fin_vigencia: date, usuario_registro: str | None = None, observacion: str | None = None) -> None:
    """Registra tarifa de operaciones por rol interno.

    Se conserva el argumento `persona` por compatibilidad con versiones previas,
    pero la regla vigente del mini sistema es: tarifa de operaciones = por rol,
    no por persona. En la tabla histórica se guarda persona='ROL' solo como
    marcador técnico.
    """
    rol_interno = (rol_interno or "").strip()
    if not rol_interno:
        raise ValueError("El rol interno es obligatorio para la tarifa de operaciones.")
    if fecha_fin_vigencia < fecha_inicio_vigencia:
        raise ValueError("La fecha fin de la tarifa de operaciones no puede ser menor que la fecha inicio.")
    _close_previous_tariff(conn, "tarifas_dw_historico", ["rol_interno"], [rol_interno], fecha_inicio_vigencia)
    conn.execute(
        """
        INSERT INTO tarifas_dw_historico(persona, rol_interno, tarifa_real_dw_hora, moneda, fecha_inicio_vigencia, fecha_fin_vigencia, estado, usuario_registro, fecha_registro, observacion)
        VALUES (?, ?, ?, ?, ?, ?, 'VIGENTE', ?, ?, ?)
        """,
        ("ROL", rol_interno, tarifa_real_dw_hora, moneda, fecha_inicio_vigencia.isoformat(), fecha_fin_vigencia.isoformat(), usuario_registro, _today_str(), observacion),
    )
    conn.commit()


def upsert_tarifa_comercial(
    conn: sqlite3.Connection,
    cliente: str | None,
    proyecto: str | None,
    rol_facturable: str | None,
    tarifa_comercial_hora: float,
    moneda: str,
    fecha_inicio_vigencia: date,
    fecha_fin_vigencia: date,
    usuario_registro: str | None = None,
    observacion: str | None = None,
) -> None:
    """Registra tarifa comercial por proyecto y rol comercial/asignado.

    Regla de negocio v19:
    - Tarifa de operaciones = por rol interno.
    - Tarifa comercial = por proyecto + rol asignado/comercial.
    - Una persona puede trabajar en varios proyectos; el monto comercial depende
      del proyecto y del rol con el que se factura en ese proyecto.
    """
    cliente = (cliente or "").strip()
    proyecto = (proyecto or "").strip()
    rol_facturable = canonicalize_facturable_role(rol_facturable or "") or (rol_facturable or "").strip()
    if not proyecto:
        raise ValueError("El proyecto es obligatorio para la tarifa comercial.")
    if not rol_facturable:
        raise ValueError("El rol comercial/asignado es obligatorio para la tarifa comercial.")
    if fecha_fin_vigencia < fecha_inicio_vigencia:
        raise ValueError("La fecha fin de la tarifa comercial no puede ser menor que la fecha inicio.")
    _close_previous_tariff(conn, "tarifas_comerciales_historico", ["proyecto", "rol_facturable"], [proyecto, rol_facturable], fecha_inicio_vigencia)
    conn.execute(
        """
        INSERT INTO tarifas_comerciales_historico(cliente, proyecto, persona, rol_facturable, tarifa_comercial_hora, moneda, fecha_inicio_vigencia, fecha_fin_vigencia, estado, usuario_registro, fecha_registro, observacion)
        VALUES (?, ?, 'PROYECTO_ROL', ?, ?, ?, ?, ?, 'VIGENTE', ?, ?, ?)
        """,
        (cliente, proyecto, rol_facturable, tarifa_comercial_hora, moneda, fecha_inicio_vigencia.isoformat(), fecha_fin_vigencia.isoformat(), usuario_registro, _today_str(), observacion),
    )
    conn.commit()



def upsert_tarifa_comercial_rol(conn: sqlite3.Connection, rol_facturable: str | None, tarifa_comercial_hora: float, moneda: str, fecha_inicio_vigencia: date, fecha_fin_vigencia: date, usuario_registro: str | None = None, observacion: str | None = None) -> None:
    """Registra tarifa comercial por rol comercial.

    Se usa principalmente en Gerencia General para calcular:
    Costo real comercial = Horas facturables × Tarifa comercial del rol.
    """
    rol_facturable = (rol_facturable or "").strip()
    if not rol_facturable:
        raise ValueError("El rol comercial es obligatorio para la tarifa comercial por rol.")
    if fecha_fin_vigencia < fecha_inicio_vigencia:
        raise ValueError("La fecha fin de la tarifa comercial no puede ser menor que la fecha inicio.")
    _close_previous_tariff(conn, "tarifas_comerciales_historico", ["rol_facturable"], [rol_facturable], fecha_inicio_vigencia)
    conn.execute(
        """
        INSERT INTO tarifas_comerciales_historico(cliente, proyecto, persona, rol_facturable, tarifa_comercial_hora, moneda, fecha_inicio_vigencia, fecha_fin_vigencia, estado, usuario_registro, fecha_registro, observacion)
        VALUES ('', '', 'ROL', ?, ?, ?, ?, ?, 'VIGENTE', ?, ?, ?)
        """,
        (rol_facturable, tarifa_comercial_hora, moneda, fecha_inicio_vigencia.isoformat(), fecha_fin_vigencia.isoformat(), usuario_registro, _today_str(), observacion),
    )
    conn.commit()

def load_tarifas_dw(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id_tarifa_dw, persona, rol_interno, tarifa_real_dw_hora, moneda, fecha_inicio_vigencia, fecha_fin_vigencia, estado, usuario_registro, fecha_registro, observacion FROM tarifas_dw_historico ORDER BY rol_interno, fecha_inicio_vigencia DESC, id_tarifa_dw DESC",
        conn,
    )


def load_tarifas_comerciales(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id_tarifa_comercial, cliente, proyecto, persona, rol_facturable, tarifa_comercial_hora, moneda, fecha_inicio_vigencia, fecha_fin_vigencia, estado, usuario_registro, fecha_registro, observacion FROM tarifas_comerciales_historico ORDER BY proyecto, rol_facturable, fecha_inicio_vigencia DESC, id_tarifa_comercial DESC",
        conn,
    )


def seed_demo_tarifas(conn: sqlite3.Connection) -> None:
    # No se cargan tarifas demo: las tarifas deben ser definidas por rol/cliente.
    return None
