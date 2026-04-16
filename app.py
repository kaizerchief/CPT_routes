import os, io, csv, json, datetime, redis, tempfile, re
from flask import Flask, render_template, request, send_file, session, redirect, url_for

# --- Vercel KV (Upstash Redis) ---
_redis_url = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
db = None
if _redis_url:
    try:
        db = redis.Redis.from_url(_redis_url, decode_responses=True)
        db.ping()
        print("OK Conectado a Vercel KV")
    except Exception as e:
        print(f"ERR Vercel KV: {e}")

FALLBACK_DIR = os.path.join(tempfile.gettempdir(), "cpt_uploads")
if not db:
    print("WARN: sin KV, usando fallback local (solo dev)")
    os.makedirs(FALLBACK_DIR, exist_ok=True)

STATE_KEY   = "routes:latest"
TTL_SECONDS = 12 * 60 * 60  # 12 horas

def save_routes_state(csv_content, params):
    now = datetime.datetime.now()
    state = {
        "upload_time": now.strftime("%d/%m/%Y %H:%M"),
        "expires_at":  (now + datetime.timedelta(seconds=TTL_SECONDS)).strftime("%d/%m/%Y %H:%M"),
        "params":      params,
        "csv_content": csv_content,
    }
    payload = json.dumps(state, ensure_ascii=False)
    if db:
        db.set(STATE_KEY, payload, ex=TTL_SECONDS)
    else:
        with open(os.path.join(FALLBACK_DIR, "state.json"), "w", encoding="utf-8") as f:
            f.write(payload)

def get_routes_state():
    try:
        if db:
            data = db.get(STATE_KEY)
            return json.loads(data) if data else None
        path = os.path.join(FALLBACK_DIR, "state.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"ERR get_state: {e}")
    return None

def delete_routes_state():
    if db:
        db.delete(STATE_KEY)
    else:
        path = os.path.join(FALLBACK_DIR, "state.json")
        if os.path.exists(path):
            os.remove(path)

# --- Flask ---
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "CptListSecureKey_2026")

COL_WIDTH_ID=25; COL_WIDTH_DESTINO=50; COL_WIDTH_MLP=55
COL_WIDTH_COND1=80; COL_WIDTH_COND2=80; COL_WIDTH_TRACTO=45
COL_WIDTH_RAMPLA=50; COL_WIDTH_CORTINA=40; COL_WIDTH_TIPO=25
COL_WIDTH_ARRIBO=20; COL_WIDTH_PARTIDA=20; COL_WIDTH_OBSERVACIONES=75

REQUIRED_COLUMNS = [
    "Destino","Transportista","Nombre del Conductor 1","Nombre del Conductor 2",
    "Vehiculo tractor","Vehiculo de carga 1","Tipo de Vehiculo","Origen ETA","Origen ETD"
]
DISPLAY_COLUMNS = [
    "#","Destino","MLP","Nombre del\nConductor 1","Nombre del\nConductor 2",
    "Tracto","Rampla","Cortina","Tipo","A","P","Observaciones"
]

def get_cpt_title(etd_val):
    if not etd_val: return "CPT Desconocido"
    time_str = etd_val.split(" ")[-1][:5] if " " in etd_val else etd_val[:5]
    try:
        h,m = map(int, time_str.split(':'))
        t = h*60+m-20
        if t<0: t+=1440
        return f"CPT de las {t//60:02d}:{t%60:02d}"
    except: return f"CPT de las {time_str}"

def cargar_ramplas():
    ramplas_set = set()
    json_path = os.path.join(BASE_DIR, "json", "ramplas.json")
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as f:
            try: ramplas_set = set(json.load(f).get("rampla", []))
            except Exception as e: print(f"ERR ramplas: {e}")
    else:
        print(f"WARN ramplas.json no encontrado en {json_path}")
    return ramplas_set

# --- Rutas ---
@app.route('/')
def start(): return render_template('start.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.environ.get('APP_PASSWORD','admin123'):
            session['logged_in'] = True
            return redirect(url_for('upload'))
        return render_template('login.html', error="Contraseña incorrecta")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('start'))

@app.route('/upload')
def upload():
    if not session.get('logged_in'): return redirect(url_for('login'))
    state = get_routes_state()
    return render_template('upload.html',
        upload_time=state.get("upload_time") if state else None,
        expires_at=state.get("expires_at") if state else None)

@app.route('/borrar_estado', methods=['POST'])
def borrar_estado():
    if not session.get('logged_in'): return "No autorizado", 401
    delete_routes_state()
    return redirect(url_for('upload'))

@app.route('/ver_rutas')
def ver_rutas():
    state = get_routes_state()
    if not state or not state.get("csv_content"):
        return render_template('ver_rutas.html', status="empty")
    try:
        processed_rows, fechas_citacion, ramplas_set = procesar_csv(state["csv_content"], state["params"])
    except Exception as e:
        return render_template('ver_rutas.html', status="error", message=str(e))
    if not processed_rows:
        return render_template('ver_rutas.html', status="empty",
                               message="No se encontraron registros tras aplicar los filtros guardados.")

    def get_base_dest(dest):
        """Extrae el prefijo base del destino (p.ej. 'SBB1' de 'SBB1(2COND)' o 'SRM2' de 'SRM2_DEDICADO')."""
        m = re.match(r'^([A-Za-z0-9]+)', str(dest).strip().upper())
        return m.group(1) if m else str(dest).strip().upper()

    # --- Vista por CPT: agrupar por ETD, luego por destino base ---
    cpt_raw = {}
    for row in processed_rows:
        etd_val = row.get("Origen ETD","").strip()
        if etd_val not in cpt_raw:
            cpt_raw[etd_val] = {"title": get_cpt_title(etd_val), "rows": []}
        tipo_raw = str(row.get("Tipo de Vehiculo","")).strip().upper()
        tipo = "LH" if tipo_raw in ["RAMPLA","RAMPLA CORTA"] else ("3/4" if tipo_raw=="CARRO" else tipo_raw)
        rampla_val = str(row.get("Vehiculo de carga 1",""))
        obs_list = ["Cortina"] if rampla_val.strip() in ramplas_set else []
        cpt_raw[etd_val]["rows"].append({
            "destino": str(row.get("Destino","")),
            "mlp":     str(row.get("Transportista","")),
            "cond1":   str(row.get("Nombre del Conductor 1","")),
            "cond2":   str(row.get("Nombre del Conductor 2","")),
            "tracto":  str(row.get("Vehiculo tractor","")),
            "rampla":  rampla_val, "tipo": tipo,
            "observaciones": ", ".join(obs_list),
        })

    cpt_groups = {}
    for etd_val, gd in cpt_raw.items():
        ts = etd_val.split(" ")[-1][:5] if " " in etd_val else etd_val[:5]
        title = gd["title"]
        if ts: title = f"{title} (Salida: {ts})"
        rows_sorted = sorted(gd["rows"], key=lambda r: r["destino"])
        dest_groups = {}
        for row in rows_sorted:
            bd = get_base_dest(row["destino"])
            if bd not in dest_groups:
                dest_groups[bd] = {"label": bd, "rows": []}
            dest_groups[bd]["rows"].append(row)
        cpt_groups[etd_val] = {"title": title, "dest_groups": dest_groups}

    # --- Vista por Zonas: agrupar por zona, luego por destino base ---
    dest_groups_def = {
        "Zona Sur":           ["SBB1","SBB2","SNU1","STM1","SVL1"],
        "Zona Centro":        ["SVP3","SIL1","STC1","SLT1","SRC1"],
        "Zona Norte":         ["SLS1","SAF1","SPO1","ELS1"],
        "Zona Metropolitana": ["SRM2","CLCCCH","CLCBXP"],
    }
    zona_groups = {}
    for g_name, g_dests in dest_groups_def.items():
        zona_raw = []
        for row in processed_rows:
            if row.get("_es_segunda_vuelta"): continue
            dest_val = str(row.get("Destino","")).upper()
            if not any(d in dest_val for d in g_dests): continue
            etd_full = str(row.get("Origen ETD",""))
            hora_salida = etd_full.split(" ")[-1][:5] if " " in etd_full else etd_full[:5]
            tipo_raw = str(row.get("Tipo de Vehiculo","")).strip().upper()
            tipo = "LH" if tipo_raw in ["RAMPLA","RAMPLA CORTA"] else ("3/4" if tipo_raw=="CARRO" else tipo_raw)
            obs_list = []
            if "SRM2" in dest_val and "DEDICADO" in str(row.get("Servicio","")).upper():
                obs_list.append("2 vueltas")
            rampla_val = str(row.get("Vehiculo de carga 1",""))
            if rampla_val.strip() in ramplas_set: obs_list.append("Cortina")
            zona_raw.append({
                "destino":      str(row.get("Destino","")),
                "mlp":          str(row.get("Transportista","")),
                "cond1":        str(row.get("Nombre del Conductor 1","")),
                "cond2":        str(row.get("Nombre del Conductor 2","")),
                "tracto":       str(row.get("Vehiculo tractor","")),
                "rampla":       rampla_val,
                "tipo":         tipo,
                "hora_salida":  hora_salida,
                "origen_etd_raw": etd_full,
                "observaciones": ", ".join(obs_list),
            })
        if zona_raw:
            zona_raw.sort(key=lambda r: (get_base_dest(r["destino"]), r["destino"], r["origen_etd_raw"]))
            dest_groups = {}
            for row in zona_raw:
                bd = get_base_dest(row["destino"])
                if bd not in dest_groups:
                    dest_groups[bd] = {"label": bd, "salidas": [], "rows": []}
                if row["hora_salida"] and row["hora_salida"] not in dest_groups[bd]["salidas"]:
                    dest_groups[bd]["salidas"].append(row["hora_salida"])
                dest_groups[bd]["rows"].append(row)
            for dg in dest_groups.values():
                dg["salidas"].sort()
            zona_groups[g_name] = dest_groups

    return render_template('ver_rutas.html', status="loaded",
        upload_time=state["upload_time"], expires_at=state.get("expires_at"),
        cpt_groups=cpt_groups, zona_groups=zona_groups)

def procesar_csv(csv_raw_text, params):
    stream = io.StringIO(csv_raw_text, newline=None)
    reader = csv.DictReader(stream)
    ramplas_set = cargar_ramplas()
    min_hora_ruta = params.get('min_hora','20:00')
    max_hora_ruta = params.get('max_hora','04:00')
    incluir_sin_placa = params.get('incluir_sin_placa', False)

    valid_rows = []; min_file_date = ""
    for row in reader:
        if row.get("Origen") != "CLRM03": continue
        if not incluir_sin_placa and row.get("Vehiculo tractor","").strip().lower() == "sin placa de tractor": continue
        valid_rows.append(row)
        eta_val = row.get("Origen ETA","").strip()
        if eta_val:
            ds = eta_val.split(" ")[0]
            if not min_file_date or ds < min_file_date: min_file_date = ds

    processed_rows = []; fechas_citacion = []
    for row in valid_rows:
        sv = str(row.get("Servicio",""))
        if "_CLRM03_" in sv: row["Destino"] = sv.split("_CLRM03_")[-1]
        eta_val = row.get("Origen ETA","").strip()
        if min_file_date and eta_val:
            ds = eta_val.split(" ")[0]
            ts = eta_val.split(" ")[-1][:5] if " " in eta_val else ""
            if ts:
                if ds == min_file_date:
                    if ts < min_hora_ruta: continue
                elif ds > min_file_date:
                    if ts > max_hora_ruta: continue
        if eta_val:
            try: fechas_citacion.append(datetime.datetime.strptime(eta_val.split(" ")[0], "%Y-%m-%d").date())
            except ValueError: pass
        if "SRM2" in str(row.get("Destino","")).upper():
            etd_val = row.get("Origen ETD","").strip()
            eta_val2 = row.get("Origen ETA","").strip()
            dp = (f"{etd_val.split(' ')[0]} " if " " in etd_val
                  else (f"{eta_val2.split(' ')[0]} " if " " in eta_val2 else ""))
            if "DEDICADO" in str(row.get("Servicio","")).upper():
                r1=dict(row); r2=dict(row)
                r1["Origen ETD"]=f"{dp}01:20:00"; r1["_es_segunda_vuelta"]=False
                r2["Origen ETD"]=f"{dp}05:20:00"; r2["_es_segunda_vuelta"]=True
                processed_rows.extend([r1,r2])
            else:
                row["Origen ETD"]=f"{dp}01:20:00"; row["_es_segunda_vuelta"]=False
                processed_rows.append(row)
        else:
            row["_es_segunda_vuelta"]=False; processed_rows.append(row)
    processed_rows.sort(key=lambda r: r.get("Origen ETD",""))
    return processed_rows, fechas_citacion, ramplas_set

@app.route('/generar', methods=['POST'])
def generar():
    if not session.get('logged_in'): return "No autorizado", 401
    if 'csv_file' not in request.files: return "No se ha subido ningún archivo CSV", 400
    file = request.files['csv_file']
    if file.filename == '': return "No se ha seleccionado ningún archivo", 400

    params = {
        "min_hora":           request.form.get('min_hora','20:00'),
        "max_hora":           request.form.get('max_hora','04:00'),
        "incluir_sin_placa":  request.form.get('incluir_sin_placa') == 'on',
        "generar_pdf":        request.form.get('generar_pdf') == 'on',
    }
    csv_raw_text = file.stream.read().decode("utf-8-sig")
    save_routes_state(csv_raw_text, params)

    processed_rows, fechas_citacion, ramplas_set = procesar_csv(csv_raw_text, params)
    if not processed_rows:
        return "No se encontraron registros válidos tras aplicar los filtros.", 404

    # Si el usuario desactivó la generación de PDF, terminar aquí
    if not params.get('generar_pdf', True):
        from flask import jsonify
        return jsonify({"status": "ok", "message": "Rutas cargadas correctamente"})

    groups = {}
    for row in processed_rows:
        etd_val = row.get("Origen ETD","").strip()
        groups.setdefault(etd_val,[]).append(row)

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter,
                            leftMargin=15,rightMargin=15,topMargin=20,bottomMargin=20)
    styles = getSampleStyleSheet()
    sn = ParagraphStyle("tn", parent=styles["Normal"], fontSize=8, leading=9, textColor=colors.black)
    sc = ParagraphStyle("tc", parent=sn, alignment=1)
    sh = ParagraphStyle("th", parent=styles["Normal"], fontSize=9, textColor=colors.whitesmoke, alignment=1)

    def mp(text, c=False): return Paragraph(text, sc if c else sn) if text else ""
    headers = [Paragraph(f"<b>{col.replace(chr(10),'<br/>')}</b>", sh) for col in DISPLAY_COLUMNS]

    story = []
    period_str = ""
    if fechas_citacion:
        meses=["Enero","Febrero","Marzo","Abril","Mayo","Junio",
               "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
        mn=min(fechas_citacion); mx=max(fechas_citacion)
        if mn==mx: period_str=f" - Turno del {mn.day} de {meses[mn.month-1]}"
        elif mn.month==mx.month: period_str=f" - Turno del {mn.day} al {mx.day} de {meses[mx.month-1]}"
        else: period_str=f" - Turno del {mn.day} de {meses[mn.month-1]} al {mx.day} de {meses[mx.month-1]}"

    ts=styles['Heading1']; ts.alignment=1
    story.append(Paragraph(f"<b>Reporte de Rutas - Origen CLRM03{period_str}</b>", ts))
    story.append(Spacer(1,15))
    ss=ParagraphStyle("s",parent=styles["Normal"],fontSize=9,leading=12,textColor=colors.black)
    story.append(Paragraph(f"<b>Total de Rutas:</b> {len(processed_rows)}", ss))
    story.append(Spacer(1,10))

    ch=[Paragraph(f"<b>{get_cpt_title(e)}</b>",sh) for e in groups]
    cv=[Paragraph(str(len(groups[e])),sc) for e in groups]
    if ch:
        ct=Table([ch,cv],hAlign='LEFT')
        ct.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#2E4053')),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,1),(-1,-1),colors.white),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        story.append(ct)
    story.append(Spacer(1,15))

    tts=ParagraphStyle("tt",parent=styles["Heading2"],fontSize=11,spaceAfter=5,spaceBefore=10,textColor=colors.darkblue)
    col_widths=[COL_WIDTH_ID,COL_WIDTH_DESTINO,COL_WIDTH_MLP,COL_WIDTH_COND1,
                COL_WIDTH_COND2,COL_WIDTH_TRACTO,COL_WIDTH_RAMPLA,COL_WIDTH_CORTINA,
                COL_WIDTH_TIPO,COL_WIDTH_ARRIBO,COL_WIDTH_PARTIDA,COL_WIDTH_OBSERVACIONES]

    for etd_val, rows_in_group in groups.items():
        cpt_title=get_cpt_title(etd_val)
        td=etd_val.split(" ")[-1][:5] if " " in etd_val else etd_val[:5]
        te=""
        try:
            h,m = map(int, td.split(':'))
            t = h*60+m-80
            if t<0: t+=1440
            te = f"{t//60:02d}:{t%60:02d}"
        except: pass
        if te and td: cpt_title=f"{cpt_title} (Citación: {te} | Salida: {td})"
        elif td: cpt_title=f"{cpt_title} (Salida: {td})"
        story.append(Paragraph(f"<b>{cpt_title}</b>",tts))
        rows_in_group.sort(key=lambda r: r.get("Destino",""))
        table_data=[headers]
        for idx,row in enumerate(rows_in_group,1):
            rd=[mp(str(idx),True)]
            for col in REQUIRED_COLUMNS:
                val=str(row.get(col,""))
                if col in ["Origen ETA","Origen ETD"]: val="[   ]"
                elif col=="Tipo de Vehiculo":
                    vu=val.strip().upper()
                    if vu in ["RAMPLA","RAMPLA CORTA"]: val="LH"
                    elif vu=="CARRO": val="3/4"
                rd.append(mp(val,True))
                if col=="Vehiculo de carga 1":
                    rd.append(mp("SI [ ]" if val.strip() in ramplas_set else "",True))
            rd.append(mp("",True)); table_data.append(rd)
        t=Table(table_data,colWidths=col_widths,repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#2E4053')),
            ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),('TEXTCOLOR',(0,1),(-1,-1),colors.black),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
            ('GRID',(0,0),(-1,-1),0.5,colors.grey),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.whitesmoke,colors.white])]))
        story.append(t); story.append(Spacer(1,10))

    doc.build(story); pdf_buffer.seek(0)
    return send_file(pdf_buffer, as_attachment=True,
        download_name=f"Rutas_CLRM03_{datetime.datetime.now().strftime('%d-%m')}.pdf",
        mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
