import os
import io
import csv
import json
import datetime
import requests
import tempfile
from flask import Flask, render_template, request, send_file, session, redirect, url_for

# Extensiones para PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# SDK de Vercel Blob
from vercel_blob import put, list as list_blobs

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CptListSecureKey_2026")

# --- CONFIGURACIÓN DE ALMACENAMIENTO ---
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
VERCEL_BLOB_OBJECT_NAME = "latest_routes_state.json"
ROUTES_STATE_TTL_SECONDS = 36000 # 10 horas

# Fallback local solo para desarrollo o fallos críticos
FALLBACK_DIR = os.path.join(tempfile.gettempdir(), "cpt_uploads")
os.makedirs(FALLBACK_DIR, exist_ok=True)

# --- FUNCIONES DE PERSISTENCIA ---

def _is_state_expired(state):
    upload_time = state.get("upload_time")
    if not upload_time:
        return True
    try:
        state_time = datetime.datetime.strptime(upload_time, "%d/%m/%Y %H:%M")
        return (datetime.datetime.now() - state_time).total_seconds() >= ROUTES_STATE_TTL_SECONDS
    except Exception:
        return False

def save_routes_state(csv_content, params):
    upload_time = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    state = {
        "upload_time": upload_time,
        "params": params,
        "csv_content": csv_content
    }
    serialized_state = json.dumps(state)

    if BLOB_TOKEN:
        try:
            print(f"[DEBUG] Guardando en Vercel Blob con {len(serialized_state)} bytes...")
            # Subir a Vercel Blob como bytes (esto crea una nueva versión del archivo)
            result = put(VERCEL_BLOB_OBJECT_NAME, serialized_state.encode('utf-8'), {"access": "public"})
            print(f"[DEBUG] put() completó exitosamente: {result}")
            return
        except Exception as e:
            print(f"[ERROR] Error guardando en Vercel Blob: {e}")
            import traceback
            traceback.print_exc()

    # Fallback local (volátil en Vercel)
    path = os.path.join(FALLBACK_DIR, VERCEL_BLOB_OBJECT_NAME)
    try:
        print(f"[DEBUG] Guardando en fallback local: {path}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(serialized_state)
        print(f"[DEBUG] Archivo local guardado exitosamente ({len(serialized_state)} bytes)")
    except Exception as e:
        print(f"[ERROR] Error guardando localmente: {e}")

def get_routes_state():
    try:
        if BLOB_TOKEN:
            print(f"[DEBUG] Intentando recuperar desde Vercel Blob...")
            # Construir URL directa del Blob (Vercel Blob usa URLs predecibles)
            # Formato: https://<hash>.public.blob.vercelusercontent.com/<filename>
            # Se obtiene del resultado de put(), pero para lectura se puede hacer GET directo
            blobs_response = list_blobs({"prefix": VERCEL_BLOB_OBJECT_NAME, "limit": 1})
            print(f"[DEBUG] list_blobs response: {blobs_response}")
            
            if blobs_response.get('blobs') and len(blobs_response['blobs']) > 0:
                blob_url = blobs_response['blobs'][0]['url']
                print(f"[DEBUG] Blob URL encontrada: {blob_url}")
                response = requests.get(blob_url)
                print(f"[DEBUG] GET response status: {response.status_code}")
                if response.status_code == 200:
                    state = json.loads(response.text)
                    print(f"[DEBUG] Estado parseado, upload_time: {state.get('upload_time')}")
                    if not _is_state_expired(state):
                        return state
                    else:
                        print(f"[DEBUG] Estado expirado")
            else:
                print(f"[DEBUG] No se encontraron blobs")
            return None

        # Fallback local
        print(f"[DEBUG] BLOB_TOKEN no configurado, usando fallback local")
        path = os.path.join(FALLBACK_DIR, VERCEL_BLOB_OBJECT_NAME)
        print(f"[DEBUG] Buscando en: {path}")
        if os.path.exists(path):
            print(f"[DEBUG] Archivo local encontrado")
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
                print(f"[DEBUG] Estado local parseado, upload_time: {state.get('upload_time')}")
                if not _is_state_expired(state):
                    print(f"[DEBUG] Estado local válido, retornando")
                    return state
                else:
                    print(f"[DEBUG] Estado local expirado")
        else:
            print(f"[DEBUG] Archivo local NO encontrado en {path}")
    except Exception as e:
        print(f"[ERROR] Error al recuperar estado: {e}")
        import traceback
        traceback.print_exc()
    return None

# --- LÓGICA DE NEGOCIO Y PROCESAMIENTO ---

REQUIRED_COLUMNS = [
    "Destino", "Transportista", "Nombre del Conductor 1", 
    "Nombre del Conductor 2", "Vehiculo tractor", "Vehiculo de carga 1", 
    "Tipo de Vehiculo", "Origen ETA", "Origen ETD"
]

DISPLAY_COLUMNS = [
    "#", "Destino", "MLP", "Nombre del\nConductor 1", 
    "Nombre del\nConductor 2", "Tracto", "Rampla", 
    "Cortina", "Tipo", "A", "P", "Observaciones"
]

# Tamaños de columnas para el PDF
COL_WIDTHS = [25, 50, 55, 80, 80, 45, 50, 40, 25, 20, 20, 75]

def get_cpt_title(etd_val):
    if not etd_val: return "CPT Desconocido"
    time_str = etd_val.split(" ")[-1][:5] if " " in etd_val else etd_val[:5]
    try:
        h, m = map(int, time_str.split(':'))
        total_mins = (h * 60 + m - 20) % (24 * 60)
        return f"CPT de las {total_mins // 60:02d}:{total_mins % 60:02d}"
    except:
        return f"CPT de las {time_str}"

def cargar_ramplas():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "json", "ramplas.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return set(json.load(f).get("rampla", []))
        except: pass
    return set()

def procesar_csv(csv_raw_text, params):
    stream = io.StringIO(csv_raw_text, newline=None)
    reader = csv.DictReader(stream)
    ramplas_set = cargar_ramplas()

    min_hora = params.get('min_hora', '20:00')
    max_hora = params.get('max_hora', '04:00')
    incluir_sin_placa = params.get('incluir_sin_placa', False)

    valid_rows = []
    min_file_date = ""
    
    rows = list(reader)
    for row in rows:
        if row.get("Origen") == "CLRM03":
            tracto = row.get("Vehiculo tractor", "").strip().lower()
            if not incluir_sin_placa and tracto == "sin placa de tractor":
                continue
            valid_rows.append(row)
            eta = row.get("Origen ETA", "").strip()
            if eta:
                date_str = eta.split(" ")[0]
                if not min_file_date or date_str < min_file_date:
                    min_file_date = date_str

    processed_rows = []
    fechas_citacion = []
    
    for row in valid_rows:
        servicio = str(row.get("Servicio", ""))
        if "_CLRM03_" in servicio:
            row["Destino"] = servicio.split("_CLRM03_")[-1]
            
        eta_val = row.get("Origen ETA", "").strip()
        if min_file_date and eta_val:
            date_str, time_str = eta_val.split(" ")[0], eta_val.split(" ")[-1][:5]
            if date_str == min_file_date and time_str < min_hora: continue
            if date_str > min_file_date and time_str > max_hora: continue
        
        if eta_val:
            try: fechas_citacion.append(datetime.datetime.strptime(eta_val.split(" ")[0], "%Y-%m-%d").date())
            except: pass
        
        # Lógica especial para SRM2 Dedicado (2 vueltas)
        dest_upper = str(row.get("Destino", "")).upper()
        if "SRM2" in dest_upper and "DEDICADO" in str(row.get("Servicio", "")).upper():
            for hora in ["01:20:00", "05:20:00"]:
                new_row = dict(row)
                new_row["Origen ETD"] = f"{eta_val.split(' ')[0]} {hora}" if eta_val else hora
                new_row["_es_segunda_vuelta"] = (hora == "05:20:00")
                processed_rows.append(new_row)
        else:
            row["_es_segunda_vuelta"] = False
            processed_rows.append(row)

    processed_rows.sort(key=lambda r: r.get("Origen ETD", ""))
    return processed_rows, fechas_citacion, ramplas_set

# --- RUTAS FLASK ---

@app.route('/')
def start():
    return render_template('start.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.environ.get('APP_PASSWORD', 'admin123'):
            session['logged_in'] = True
            return redirect(url_for('upload'))
        return render_template('login.html', error="Contraseña incorrecta")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('start'))

@app.route('/upload')
def upload():
    if not session.get('logged_in'): return redirect(url_for('login'))
    state = get_routes_state()
    return render_template('upload.html', upload_time=state.get("upload_time") if state else None)

@app.route('/ver_rutas')
def ver_rutas():
    state = get_routes_state()
    if not state: return render_template('ver_rutas.html', status="empty")
    
    rows, _, ramplas = procesar_csv(state["csv_content"], state["params"])
    
    cpt_groups = {}
    for row in rows:
        etd = row.get("Origen ETD", "").strip()
        if etd not in cpt_groups:
            cpt_groups[etd] = {"title": get_cpt_title(etd), "rows": []}
        
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
    
    return render_template('ver_rutas.html', status="loaded", cpt_groups=cpt_groups, upload_time=state["upload_time"])

@app.route('/generar', methods=['POST'])
def generar():
    if not session.get('logged_in'): return "No autorizado", 401
    file = request.files.get('csv_file')
    if not file: return "Archivo requerido", 400

    params = {
        "min_hora": request.form.get('min_hora', '20:00'),
        "max_hora": request.form.get('max_hora', '04:00'),
        "incluir_sin_placa": request.form.get('incluir_sin_placa') == 'on'
    }
    
    csv_text = file.read().decode("utf-8-sig")
    save_routes_state(csv_text, params)
    
    processed_rows, fechas, ramplas = procesar_csv(csv_text, params)
    
    # Generación de PDF (ReportLab)
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=15, rightMargin=15, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    
    # Título
    title = f"<b>Reporte de Rutas - CLRM03</b>"
    story.append(Paragraph(title, styles['Heading1']))
    story.append(Spacer(1, 12))
    
    # Agrupar para el PDF
    groups = {}
    for r in processed_rows:
        etd = r.get("Origen ETD", "")
        if etd not in groups: groups[etd] = []
        groups[etd].append(r)

    header_style = ParagraphStyle("h", fontSize=9, textColor=colors.whitesmoke, alignment=1)
    cell_style = ParagraphStyle("c", fontSize=8, alignment=1)

    for etd, rows_group in groups.items():
        story.append(Paragraph(f"<b>{get_cpt_title(etd)}</b>", styles['Heading2']))
        table_data = [[Paragraph(f"<b>{h}</b>", header_style) for h in DISPLAY_COLUMNS]]
        
        for idx, row in enumerate(rows_group, 1):
            table_data.append([
                Paragraph(str(idx), cell_style),
                Paragraph(row.get("Destino", ""), cell_style),
                Paragraph(row.get("Transportista", ""), cell_style),
                Paragraph(row.get("Nombre del Conductor 1", ""), cell_style),
                Paragraph(row.get("Nombre del Conductor 2", ""), cell_style),
                Paragraph(row.get("Vehiculo tractor", ""), cell_style),
                Paragraph(row.get("Vehiculo de carga 1", ""), cell_style),
                Paragraph("SI" if row.get("Vehiculo de carga 1", "").strip() in ramplas else "", cell_style),
                Paragraph(row.get("Tipo de Vehiculo", ""), cell_style),
                "[  ]", "[  ]", ""
            ])
            
        t = Table(table_data, colWidths=COL_WIDTHS, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2E4053')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(t)
        story.append(Spacer(1, 15))

    doc.build(story)
    pdf_buffer.seek(0)
    return send_file(pdf_buffer, as_attachment=True, download_name="reporte.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)