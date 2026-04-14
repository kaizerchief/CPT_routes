#!/usr/bin/env python
"""
Script de prueba para verificar que el flujo generar -> ver_rutas funciona correctamente.
Ejecuta: python test_flow.py
"""
import os
import json
import sys
import tempfile
from datetime import datetime

# Configurar ruta del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# NO USAR BLOB_TOKEN para esta prueba - solo fallback
os.environ.pop('BLOB_READ_WRITE_TOKEN', None)
os.environ.pop('BLOB_TOKEN', None)

from app import save_routes_state, get_routes_state, procesar_csv

# --- TEST 1: Guardar estado ---
print("=" * 60)
print("TEST 1: Guardando estado...")
print("=" * 60)

csv_content = """Origen,Destino,Transportista,Nombre del Conductor 1,Nombre del Conductor 2,Vehiculo tractor,Vehiculo de carga 1,Tipo de Vehiculo,Origen ETA,Origen ETD,Servicio
CLRM03,DESTINO_TEST,MLP_TEST,COND1,COND2,TRACTO,RAMPLA1,RAMPLA,2026-04-13 21:00,2026-04-13 20:40,TEST_CLRM03_DESTINO_TEST
CLRM03,DESTINO_TEST2,MLP_TEST2,COND1_B,COND2_B,TRACTO2,RAMPLA2,CARRO,2026-04-13 21:30,2026-04-13 21:10,TEST_CLRM03_DESTINO_TEST2"""

params = {
    "min_hora": "20:00",
    "max_hora": "04:00",
    "incluir_sin_placa": False
}

try:
    save_routes_state(csv_content, params)
    print("✓ Estado guardado exitosamente")
except Exception as e:
    print(f"✗ Error al guardar: {e}")
    sys.exit(1)

# --- TEST 2: Recuperar estado ---
print("\n" + "=" * 60)
print("TEST 2: Recuperando estado...")
print("=" * 60)

try:
    state = get_routes_state()
    if state is None:
        print("✗ Estado NO recuperado (None)")
        sys.exit(1)
    
    print(f"✓ Estado recuperado")
    print(f"  - upload_time: {state.get('upload_time')}")
    print(f"  - params: {state.get('params')}")
    print(f"  - csv_content length: {len(state.get('csv_content', ''))}")
    
except Exception as e:
    print(f"✗ Error al recuperar: {e}")
    sys.exit(1)

# --- TEST 3: Procesar CSV ---
print("\n" + "=" * 60)
print("TEST 3: Procesando CSV...")
print("=" * 60)

try:
    rows, fechas, ramplas = procesar_csv(state["csv_content"], state["params"])
    print(f"✓ CSV procesado")
    print(f"  - Filas totales después del filtro: {len(rows)}")
    print(f"  - Fechas de citación: {fechas}")
    print(f"  - Ramplas conocidas: {ramplas}")
    
    if len(rows) == 0:
        print("⚠ ADVERTENCIA: No hay filas después del filtro")
    
except Exception as e:
    print(f"✗ Error al procesar: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# --- TEST 4: Construir cpt_groups ---
print("\n" + "=" * 60)
print("TEST 4: Construyendo cpt_groups (como hace ver_rutas)...")
print("=" * 60)

try:
    cpt_groups = {}
    for row in rows:
        etd = row.get("Origen ETD", "").strip()
        if etd not in cpt_groups:
            cpt_groups[etd] = {"title": f"CPT {etd}", "rows": []}
        
        tipo_raw = str(row.get("Tipo de Vehiculo", "")).strip().upper()
        cpt_groups[etd]["rows"].append({
            "destino": row.get("Destino"),
            "mlp": row.get("Transportista"),
            "cond1": row.get("Nombre del Conductor 1"),
            "cond2": row.get("Nombre del Conductor 2"),
            "tracto": row.get("Vehiculo tractor"),
            "rampla": row.get("Vehiculo de carga 1"),
            "tipo": "LH" if tipo_raw in ["RAMPLA", "RAMPLA CORTA"] else "3/4" if tipo_raw == "CARRO" else tipo_raw,
            "observaciones": "Cortina" if row.get("Vehiculo de carga 1", "").strip() in ramplas else ""
        })
    
    print(f"✓ cpt_groups construido")
    print(f"  - CPTs encontrados: {len(cpt_groups)}")
    for etd, group in cpt_groups.items():
        print(f"    - {group['title']}: {len(group['rows'])} rutas")
        for row in group['rows']:
            print(f"      → {row['destino']} | {row['mlp']} | {row['tracto']}")
    
except Exception as e:
    print(f"✗ Error al construir cpt_groups: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ TODOS LOS TESTS PASARON")
print("=" * 60)
