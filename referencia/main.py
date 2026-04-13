import csv
import os
import sys
import subprocess
import datetime
import json
import io
import re

def ensure_pymupdf():
    try:
        import fitz
    except ImportError:
        print("Instalando la librería 'pymupdf' para generar imágenes...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf"])

ensure_pymupdf()
import fitz

# Horas de Corte, MIN_HORA es respecto al dia actual y MAX_HORA respecto al dia siguiente
MIN_HORA_RUTA = "20:00"
MAX_HORA_RUTA_SIGUIENTE_DIA = "04:00"
# Permite incluir o excluir rutas que tengan 'sin placa de tractor' como tractor
INCLUIR_SIN_PLACA_TRACTOR = False

# Tamaños de las columnas del PDF (Suma total recomendada ~565 puntos)
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

def ensure_reportlab():
    try:
        import reportlab
    except ImportError:
        print("Instalando la librería 'reportlab' para generar el PDF...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])

ensure_reportlab()

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def get_cpt_title(etd_val):
    if not etd_val:
        return "CPT Desconocido"
    # Extraer la hora HH:MM
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

def main():
    import glob
    
    # Limpiar PDFs anteriores
    for pdf_file in glob.glob("Rutas_CLRM03_*.pdf"):
        try:
            os.remove(pdf_file)
            print(f"Limpiando PDF anterior: {pdf_file}")
        except Exception as e:
            pass

    images_dir = "images_v2"
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)
    else:
        # Limpiar imágenes anteriores
        for img_file in glob.glob(os.path.join(images_dir, "*.png")):
            try:
                os.remove(img_file)
            except Exception as e:
                pass


    csv_dir = "csv"
    if not os.path.exists(csv_dir):
        print(f"No se encontró la carpeta '{csv_dir}' en el directorio raíz.")
        return

    csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
    if not csv_files:
        print(f"No hay archivos CSV dentro de la carpeta '{csv_dir}'.")
        return

    csv_path = os.path.join(csv_dir, csv_files[0]) # Toma el primer CSV
    print(f"Procesando archivo: {csv_path}")

    ramplas_set = set()
    json_path = os.path.join("json", "ramplas.json")
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                ramplas_set = set(data.get("rampla", []))
            except Exception as e:
                print(f"Error al leer ramplas.json: {e}")
    else:
        print(f"Advertencia: No se encontró {json_path}")

    # Columnas exactas que existen en el CSV
    required_columns = [
        "Destino",
        "Transportista", 
        "Nombre del Conductor 1", 
        "Nombre del Conductor 2", 
        "Vehiculo tractor", 
        "Vehiculo de carga 1", 
        "Tipo de Vehiculo", 
        "Origen ETA", 
        "Origen ETD"
    ]

    # Nombre de las columnas para mostrar en el PDF
    display_columns = [
        "#",
        "Destino",
        "MLP", 
        "Nombre del\nConductor 1", 
        "Nombre del\nConductor 2", 
        "Tracto", 
        "Rampla", 
        "Cortina",
        "Tipo", 
        "A", 
        "P",
        "Observaciones"
    ]

    styles = getSampleStyleSheet()
    
    style_normal = ParagraphStyle(
        "table_normal",
        parent=styles["Normal"],
        fontSize=8,
        leading=9,
        textColor=colors.black
    )
    
    style_centered = ParagraphStyle(
        "table_centered",
        parent=style_normal,
        alignment=1
    )

    # Función auxiliar para permitir saltos de línea largos dentro de las celdas
    def make_paragraph(text, is_centered=False):
        if not text:
            return ""
        return Paragraph(text, style_centered if is_centered else style_normal)

    # Encabezados
    header_style = ParagraphStyle(
        "table_header",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.whitesmoke,
        alignment=1
    )
    
    headers = [Paragraph(f"<b>{col.replace(chr(10), '<br/>')}</b>", header_style) for col in display_columns]

    # Lectura del archivo y filtrado
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        
        # Validar si las columnas existen
        if reader.fieldnames:
            cols_to_check = required_columns + ["Servicio"]
            missing_cols = [c for c in cols_to_check if c not in reader.fieldnames]
            if missing_cols:
                print(f"Advertencia: Faltan las siguientes columnas en el CSV: {missing_cols}")
        
        valid_rows = []
        min_file_date = ""
        
        for row in reader:
            if row.get("Origen") == "CLRM03":
                tracto_val = row.get("Vehiculo tractor", "").strip().lower()
                if not INCLUIR_SIN_PLACA_TRACTOR and tracto_val == "sin placa de tractor":
                    continue
                valid_rows.append(row)
                
                eta_val = row.get("Origen ETA", "").strip()
                if eta_val:
                    date_str = eta_val.split(" ")[0]
                    if not min_file_date or date_str < min_file_date:
                        min_file_date = date_str

        # Construir la tabla con las filas válidas y aplicar los nuevos filtros de hora
        processed_rows = []
        fechas_citacion = []
        
        for row in valid_rows:
            # Usar la columna Servicio para establecer el nuevo Destino
            servicio_val = str(row.get("Servicio", ""))
            if "_CLRM03_" in servicio_val:
                row["Destino"] = servicio_val.split("_CLRM03_")[-1]
                
            eta_val = row.get("Origen ETA", "").strip()
            
            if min_file_date and eta_val:
                date_str = eta_val.split(" ")[0]
                time_str = eta_val.split(" ")[-1][:5] if " " in eta_val else ""
                
                if time_str:
                    # Si es del día inicial, descartar si es antes de la hora mínima
                    if date_str == min_file_date:
                        if time_str < MIN_HORA_RUTA:
                            continue
                    # Si es de un día posterior, descartar si es después de la hora máxima del día siguiente
                    elif date_str > min_file_date:
                        if time_str > MAX_HORA_RUTA_SIGUIENTE_DIA:
                            continue
            
            if eta_val:
                date_str = eta_val.split(" ")[0]
                try:
                    fechas_citacion.append(datetime.datetime.strptime(date_str, "%Y-%m-%d").date())
                except ValueError:
                    pass
            
            # Crear ambas vueltas para SRM2 si aplica
            if "SRM2" in str(row.get("Destino", "")).upper():
                # Construir fechas para el ETD basándose en la fecha del ETD original o ETA
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
        print("No se encontraron registros que coincidan con Origen = 'CLRM03' después de los filtros.")
        return

    # Agrupar las filas por Origen ETD
    processed_rows.sort(key=lambda r: r.get("Origen ETD", ""))
    groups = {}
    for row in processed_rows:
        etd_val = row.get("Origen ETD", "").strip()
        if etd_val not in groups:
            groups[etd_val] = []
        groups[etd_val].append(row)

    output_pdf = f"Rutas_CLRM03_{datetime.datetime.now().strftime('%d-%m')}.pdf"
    doc = SimpleDocTemplate(
        output_pdf, 
        pagesize=letter, 
        leftMargin=15, 
        rightMargin=15, 
        topMargin=20, 
        bottomMargin=20
    )
    
    # Ajuste col_widths usando las constantes definidas al inicio
    col_widths = [
        COL_WIDTH_ID, COL_WIDTH_DESTINO, COL_WIDTH_MLP, COL_WIDTH_COND1, 
        COL_WIDTH_COND2, COL_WIDTH_TRACTO, COL_WIDTH_RAMPLA, COL_WIDTH_CORTINA, 
        COL_WIDTH_TIPO, COL_WIDTH_ARRIBO, COL_WIDTH_PARTIDA, COL_WIDTH_OBSERVACIONES
    ]
    
    story = []
    
    # Determinar el string del periodo
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

    # Título del documento
    title_style = styles['Heading1']
    title_style.alignment = 1
    story.append(Paragraph(f"<b>Reporte de Rutas - Origen CLRM03{period_str}</b>", title_style))
    story.append(Spacer(1, 15))
    
    summary_title_style = ParagraphStyle(
        "summary_title",
        parent=styles["Heading3"],
        fontSize=11,
        spaceAfter=5,
        textColor=colors.black
    )
    summary_text_style = ParagraphStyle(
        "summary_text",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.black
    )
    story.append(Paragraph(f"<b>Total de Rutas:</b> {len(processed_rows)}", summary_text_style))
    story.append(Spacer(1, 10))
    
    cpt_headers = []
    cpt_values = []
    for etd_val, rows_in_group in groups.items():
        cpt_headers.append(Paragraph(f"<b>{get_cpt_title(etd_val)}</b>", header_style))
        cpt_values.append(Paragraph(str(len(rows_in_group)), style_centered))
        
    if cpt_headers:
        cpt_table_data = [cpt_headers, cpt_values]
        cpt_table = Table(cpt_table_data, hAlign='LEFT')
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

    table_title_style = ParagraphStyle(
        "table_title",
        parent=styles["Heading2"],
        fontSize=11,
        spaceAfter=5,
        spaceBefore=10,
        textColor=colors.darkblue
    )

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
        
        # Ordenar las rutas de cada grupo por Destino
        rows_in_group.sort(key=lambda r: r.get("Destino", ""))
        
        table_data = []
        table_data_img = []
        
        table_data.append(headers)
        table_data_img.append(headers[:-3])
        
        for idx, row in enumerate(rows_in_group, start=1):
            row_data = [make_paragraph(str(idx), is_centered=True)]
            row_data_img = [make_paragraph(str(idx), is_centered=True)]
            
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
                if col not in ["Origen ETA", "Origen ETD"]:
                    row_data_img.append(make_paragraph(val, is_centered=True))
                
                if col == "Vehiculo de carga 1":
                    cortina_val = "SI [ ]" if val.strip() in ramplas_set else ""
                    row_data.append(make_paragraph(cortina_val, is_centered=True))
                    row_data_img.append(make_paragraph(cortina_val, is_centered=True))

            # Agregar celda en blanco para la columna Observaciones
            row_data.append(make_paragraph("", is_centered=True))
            
            table_data.append(row_data)
            table_data_img.append(row_data_img)

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_img = Table(table_data_img, colWidths=col_widths[:-3], repeatRows=1)
        
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E4053')),   # cabecera oscura
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),             # texto cabecera blanco
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),                 # texto negro en el resto de la tabla
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white])
        ])
        
        t.setStyle(table_style)
        t_img.setStyle(table_style)
        
        story.append(t)
        story.append(Spacer(1, 10))
        
        # --- ELIMINADA LA GENERACIÓN DE IMAGEN POR CPT ---

    
    doc.build(story)
    print(f"PDF generado correctamente -> {output_pdf}")

    # --- GENERAR IMÁGENES V2 POR GRUPO DE DESTINO ---
    dest_groups = {
        "Zona Sur": ["SBB1", "SBB2", "SNU1", "STM1", "SVL1"],
        "Zona Centro": ["SVP3", "SIL1", "STC1", "SLT1", "SRC1"],
        "Zona Norte": ["SLS1", "SAF1", "SPO1", "ELS1"],
        "Zona Metropolitana": ["SRM2", "CLCCCH", "CLCBXP"]
    }
    
    img_headers = ["Destino", "MLP", "Nombre del\nConductor 1", "Nombre del\nConductor 2", "Tracto", "Rampla", "Hora de\nSalida", "Observaciones"]
    img_col_widths = [COL_WIDTH_DESTINO, COL_WIDTH_MLP, COL_WIDTH_COND1, COL_WIDTH_COND2, COL_WIDTH_TRACTO, COL_WIDTH_RAMPLA, 50, COL_WIDTH_OBSERVACIONES]
    hdr_cells = [Paragraph(f"<b>{col.replace(chr(10), '<br/>')}</b>", header_style) for col in img_headers]
    
    for g_name, g_dests in dest_groups.items():
        # Filtrar filas que contengan alguno de los destinos en su nombre
        g_rows = []
        for r in processed_rows:
            if r.get("_es_segunda_vuelta", False):
                continue
            dest_val = str(r.get("Destino", "")).upper()
            if any(d in dest_val for d in g_dests):
                g_rows.append(r)
        
        if not g_rows:
            continue
            
        # Agrupados por destino desde los que salen primero a los que salen de ultimo, en base a Hora de Salida
        g_rows.sort(key=lambda r: (r.get("Destino", ""), r.get("Origen ETD", "")))
        
        table_data = [hdr_cells]
        for row in g_rows:
            dest_val = str(row.get("Destino", ""))
            mlp_val = str(row.get("Transportista", ""))
            cond1 = str(row.get("Nombre del Conductor 1", ""))
            cond2 = str(row.get("Nombre del Conductor 2", ""))
            tracto = str(row.get("Vehiculo tractor", ""))
            rampla = str(row.get("Vehiculo de carga 1", ""))
            etd_full = str(row.get("Origen ETD", ""))
            hora_salida = etd_full.split(" ")[-1][:5] if " " in etd_full else etd_full[:5]
            
            obs = ""
            servicio_val = str(row.get("Servicio", "")).upper()
            if "SRM2" in dest_val.upper() and "DEDICADO" in servicio_val:
                obs = "2 vueltas"
                
            row_cells = [
                make_paragraph(dest_val, is_centered=True),
                make_paragraph(mlp_val, is_centered=True),
                make_paragraph(cond1, is_centered=True),
                make_paragraph(cond2, is_centered=True),
                make_paragraph(tracto, is_centered=True),
                make_paragraph(rampla, is_centered=True),
                make_paragraph(hora_salida, is_centered=True),
                make_paragraph(obs, is_centered=True),
            ]
            table_data.append(row_cells)
            
        t_img = Table(table_data, colWidths=img_col_widths, repeatRows=1)
        # Reutilizar el estilo de tabla
        t_img.setStyle(TableStyle([
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
        
        p_title = Paragraph(f"<b>Rutas - {g_name}</b>", table_title_style)
        cpt_story = [p_title, t_img]
        
        w_t, h_t = t_img.wrap(0, 0)
        w_p, h_p = p_title.wrap(w_t, 0)
        page_width = w_t + 30
        page_height = h_t + h_p + 60
        
        cpt_pdf_buffer = io.BytesIO()
        cpt_doc = SimpleDocTemplate(
            cpt_pdf_buffer, 
            pagesize=(page_width, page_height), 
            leftMargin=15, 
            rightMargin=15, 
            topMargin=15, 
            bottomMargin=15
        )
        cpt_doc.build(cpt_story)
        
        cpt_pdf_buffer.seek(0)
        cpt_fitz_doc = fitz.open(stream=cpt_pdf_buffer.read(), filetype="pdf")
        if len(cpt_fitz_doc) > 0:
            page = cpt_fitz_doc[0] # asumiendo que cabe en 1 hoja, o iterar si hay multi-paginas
            # si puede haber varias páginas, mejor iterar:
        for page_idx in range(len(cpt_fitz_doc)):
            page_fitz = cpt_fitz_doc[page_idx]
            pix = page_fitz.get_pixmap(dpi=150)
            suffix_idx = f"_{page_idx+1}" if len(cpt_fitz_doc) > 1 else ""
            img_filename = os.path.join(images_dir, f"{g_name.replace(' ', '_')}{suffix_idx}.png")
            pix.save(img_filename)
            print(f"Imagen destino v2 -> {img_filename}")
    # -----------------------------------------------------------


if __name__ == "__main__":
    main()