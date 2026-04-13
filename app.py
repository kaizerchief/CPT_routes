import os
import io
import csv
import json
import datetime
from flask import Flask, render_template, request, send_file, session, redirect, url_for

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CptListSecureKey_2026")

# Tamaños de las columnas del PDF
COL_WIDTH_ID = 25
COL_WIDTH_DESTINO = 50
COL_WIDTH_MLP = 55
COL_WIDTH_COND1 = 80
COL_WIDTH_COND2 = 80
COL_WIDTH_TRACTO = 45
COL_WIDTH_RAMPLA = 50
COL_WIDTH_CORTINA = 40
COL_WIDTH_TIPO = 25
COL_WIDTH_ARRIBO = 20
COL_WIDTH_PARTIDA = 20
COL_WIDTH_OBSERVACIONES = 75

def get_cpt_title(etd_val):
    if not etd_val:
        return "CPT Desconocido"
    if " " in etd_val:
        time_str = etd_val.split(" ")[-1][:5]
    else:
        time_str = etd_val[:5]
    
    try:
        h, m = map(int, time_str.split(':'))
        total_mins = h * 60 + m - 20
        if total_mins < 0:
            total_mins += 24 * 60
        new_h = total_mins // 60
        new_m = total_mins % 60
        return f"CPT de las {new_h:02d}:{new_m:02d}"
    except Exception:
        return f"CPT de las {time_str}"

def cargar_ramplas():
    ramplas_set = set()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "json", "ramplas.json")
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                ramplas_set = set(data.get("rampla", []))
            except Exception as e:
                print(f"Error al leer ramplas.json: {e}")
    return ramplas_set

@app.route('/')
def start():
    return render_template('start.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        master_password = os.environ.get('APP_PASSWORD', 'admin123')
        if password == master_password:
            session['logged_in'] = True
            return redirect(url_for('upload'))
        else:
            return render_template('login.html', error="Contraseña incorrecta")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('start'))

@app.route('/upload')
def upload():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('upload.html')

@app.route('/ver_rutas')
def ver_rutas():
    # Opción 2: Pública por ahora
    return "<h2>Opción 2: Ver rutas cargadas (En construcción)</h2><a href='/'>Volver al inicio</a>"

@app.route('/generar', methods=['POST'])
def generar():
    if not session.get('logged_in'):
        return "No autorizado", 401

    if 'csv_file' not in request.files:
        return "No se ha subido ningún archivo CSV", 400
        
    file = request.files['csv_file']
    if file.filename == '':
        return "No se ha seleccionado ningún archivo", 400

    min_hora_ruta = request.form.get('min_hora', '20:00')
    max_hora_ruta = request.form.get('max_hora', '04:00')
    incluir_sin_placa = request.form.get('incluir_sin_placa') == 'on'
    
    # Leer el stream como string CSV
    stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
    reader = csv.DictReader(stream)

    ramplas_set = cargar_ramplas()

    required_columns = [
        "Destino", "Transportista", "Nombre del Conductor 1", 
        "Nombre del Conductor 2", "Vehiculo tractor", "Vehiculo de carga 1", 
        "Tipo de Vehiculo", "Origen ETA", "Origen ETD"
    ]

    display_columns = [
        "#", "Destino", "MLP", "Nombre del\nConductor 1", 
        "Nombre del\nConductor 2", "Tracto", "Rampla", 
        "Cortina", "Tipo", "A", "P", "Observaciones"
    ]

    valid_rows = []
    min_file_date = ""
    
    for row in reader:
        if row.get("Origen") == "CLRM03":
            tracto_val = row.get("Vehiculo tractor", "").strip().lower()
            if not incluir_sin_placa and tracto_val == "sin placa de tractor":
                continue
            valid_rows.append(row)
            
            eta_val = row.get("Origen ETA", "").strip()
            if eta_val:
                date_str = eta_val.split(" ")[0]
                if not min_file_date or date_str < min_file_date:
                    min_file_date = date_str

    processed_rows = []
    fechas_citacion = []
    
    for row in valid_rows:
        servicio_val = str(row.get("Servicio", ""))
        if "_CLRM03_" in servicio_val:
            row["Destino"] = servicio_val.split("_CLRM03_")[-1]
            
        eta_val = row.get("Origen ETA", "").strip()
        
        if min_file_date and eta_val:
            date_str = eta_val.split(" ")[0]
            time_str = eta_val.split(" ")[-1][:5] if " " in eta_val else ""
            
            if time_str:
                if date_str == min_file_date:
                    if time_str < min_hora_ruta:
                        continue
                elif date_str > min_file_date:
                    if time_str > max_hora_ruta:
                        continue
        
        if eta_val:
            date_str = eta_val.split(" ")[0]
            try:
                fechas_citacion.append(datetime.datetime.strptime(date_str, "%Y-%m-%d").date())
            except ValueError:
                pass
        
        if "SRM2" in str(row.get("Destino", "")).upper():
            etd_val = row.get("Origen ETD", "").strip()
            date_prefix = ""
            if " " in etd_val:
                date_prefix = f"{etd_val.split(' ')[0]} "
            elif " " in eta_val:
                date_prefix = f"{eta_val.split(' ')[0]} "
            
            servicio_val = str(row.get("Servicio", "")).upper()
            if "DEDICADO" in servicio_val:
                row_v1 = dict(row)
                row_v2 = dict(row)
                row_v1["Origen ETD"] = f"{date_prefix}01:20:00"
                row_v2["Origen ETD"] = f"{date_prefix}05:20:00"
                row_v1["_es_segunda_vuelta"] = False
                row_v2["_es_segunda_vuelta"] = True
                processed_rows.append(row_v1)
                processed_rows.append(row_v2)
            else:
                row["Origen ETD"] = f"{date_prefix}01:20:00"
                row["_es_segunda_vuelta"] = False
                processed_rows.append(row)
        else:
            row["_es_segunda_vuelta"] = False
            processed_rows.append(row)

    if not processed_rows:
        return "No se encontraron registros válidos tras aplicar los filtros. Comprueba las fechas o las horas ingresadas.", 404

    processed_rows.sort(key=lambda r: r.get("Origen ETD", ""))
    groups = {}
    for row in processed_rows:
        if row.get("_es_segunda_vuelta", False):
            pass # No ignorar, es parte del reporte original, los filtros de imagenes ya no estan.
        etd_val = row.get("Origen ETD", "").strip()
        if etd_val not in groups:
            groups[etd_val] = []
        groups[etd_val].append(row)

    # Preparar PDF en memoria
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer, 
        pagesize=letter, 
        leftMargin=15, rightMargin=15, topMargin=20, bottomMargin=20
    )
    
    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle("table_normal", parent=styles["Normal"], fontSize=8, leading=9, textColor=colors.black)
    style_centered = ParagraphStyle("table_centered", parent=style_normal, alignment=1)
    
    def make_paragraph(text, is_centered=False):
        if not text: return ""
        return Paragraph(text, style_centered if is_centered else style_normal)

    header_style = ParagraphStyle("table_header", parent=styles["Normal"], fontSize=9, textColor=colors.whitesmoke, alignment=1)
    headers = [Paragraph(f"<b>{col.replace(chr(10), '<br/>')}</b>", header_style) for col in display_columns]

    story = []
    
    period_str = ""
    if fechas_citacion:
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        min_date = min(fechas_citacion)
        max_date = max(fechas_citacion)
        if min_date == max_date:
            period_str = f" - Turno del {min_date.day} de {meses[min_date.month - 1]}"
        elif min_date.month == max_date.month:
            period_str = f" - Turno del {min_date.day} al {max_date.day} de {meses[max_date.month - 1]}"
        else:
            period_str = f" - Turno del {min_date.day} de {meses[min_date.month - 1]} al {max_date.day} de {meses[max_date.month - 1]}"

    title_style = styles['Heading1']
    title_style.alignment = 1
    story.append(Paragraph(f"<b>Reporte de Rutas - Origen CLRM03{period_str}</b>", title_style))
    story.append(Spacer(1, 15))
    
    summary_text_style = ParagraphStyle("summary_text", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.black)
    story.append(Paragraph(f"<b>Total de Rutas:</b> {len(processed_rows)}", summary_text_style))
    story.append(Spacer(1, 10))
    
    cpt_headers = []
    cpt_values = []
    for etd_val, rows_in_group in groups.items():
        cpt_headers.append(Paragraph(f"<b>{get_cpt_title(etd_val)}</b>", header_style))
        cpt_values.append(Paragraph(str(len(rows_in_group)), style_centered))
        
    if cpt_headers:
        cpt_table = Table([cpt_headers, cpt_values], hAlign='LEFT')
        cpt_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E4053')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4)
        ]))
        story.append(cpt_table)

    story.append(Spacer(1, 15))
    table_title_style = ParagraphStyle("table_title", parent=styles["Heading2"], fontSize=11, spaceAfter=5, spaceBefore=10, textColor=colors.darkblue)

    col_widths = [
        COL_WIDTH_ID, COL_WIDTH_DESTINO, COL_WIDTH_MLP, COL_WIDTH_COND1, 
        COL_WIDTH_COND2, COL_WIDTH_TRACTO, COL_WIDTH_RAMPLA, COL_WIDTH_CORTINA, 
        COL_WIDTH_TIPO, COL_WIDTH_ARRIBO, COL_WIDTH_PARTIDA, COL_WIDTH_OBSERVACIONES
    ]

    for etd_val, rows_in_group in groups.items():
        cpt_title = get_cpt_title(etd_val)
        eta_val = rows_in_group[0].get("Origen ETA", "").strip()
        time_str_eta = eta_val.split(" ")[-1][:5] if " " in eta_val else eta_val[:5]
        time_str_etd = etd_val.split(" ")[-1][:5] if " " in etd_val else etd_val[:5]
        
        if time_str_eta and time_str_etd:
            cpt_title = f"{cpt_title} (Citación: {time_str_eta} | Salida: {time_str_etd})"
        elif time_str_etd:
            cpt_title = f"{cpt_title} (Salida: {time_str_etd})"
            
        story.append(Paragraph(f"<b>{cpt_title}</b>", table_title_style))
        rows_in_group.sort(key=lambda r: r.get("Destino", ""))
        
        table_data = [headers]
        
        for idx, row in enumerate(rows_in_group, start=1):
            row_data = [make_paragraph(str(idx), is_centered=True)]
            
            for col in required_columns:
                val = str(row.get(col, ""))
                if col in ["Origen ETA", "Origen ETD"]:
                    val = "[   ]"
                elif col == "Tipo de Vehiculo":
                    val_up = val.strip().upper()
                    if val_up in ["RAMPLA", "RAMPLA CORTA"]:
                        val = "LH"
                    elif val_up == "CARRO":
                        val = "3/4"
                        
                row_data.append(make_paragraph(val, is_centered=True))
                
                if col == "Vehiculo de carga 1":
                    cortina_val = "SI [ ]" if val.strip() in ramplas_set else ""
                    row_data.append(make_paragraph(cortina_val, is_centered=True))

            row_data.append(make_paragraph("", is_centered=True))
            table_data.append(row_data)

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E4053')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white])
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    doc.build(story)
    pdf_buffer.seek(0)
    
    nombre_archivo = f"Rutas_CLRM03_{datetime.datetime.now().strftime('%d-%m')}.pdf"
    
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype='application/pdf'
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)
