# DW Manager v20

Mini sistema Streamlit + SQLite para cargar Excel de ClickUp y analizar horas, tarifas, costos y resultado operativo.

## Flujo

1. Cargar Excel ClickUp.
2. Registrar tarifas:
   - Tarifa de operaciones: por rol interno.
   - Tarifa comercial: por proyecto + rol asignado/comercial.
3. Revisar Gerencia General.
4. Revisar Gerencia de Servicios.
5. Descargar reportes Excel.

## Cambios v20

- En Tarifas ya no se muestran fechas en los formularios ni en las tablas. La vigencia se mantiene internamente.
- En Gerencia General se retiró la tarjeta de reglas de cálculo.
- Los KPIs se ordenaron: primero horas, luego progreso por proyecto y después dinero.
- En Gerencia de Servicios se evita mostrar costo real comercial en gráficos y tablas.
- Corrección para evitar error de tablas por columnas visibles duplicadas.

## Ejecución

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Si PowerShell bloquea la activación:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```
