# utils/computo_processor.py
import pdfplumber
import json
import logging
from typing import Dict, Any, List
from datetime import date

# Import per generazione PDF (da Cella 7)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)

# Logger
log = logging.getLogger("computo_processor")

# --- Logica Cella 2: Estrazione da PDF ---

# Schema di estrazione (specifico per questo modulo)
TARGET_SCHEMA_EXTRACTION = {
  "_id": "",
  "metadata": {
    "document_title": "", "subject": "", "client": "", "location": "",
    "project_manager": "", "technician": "", "date": ""
  },
  "bill_of_quantities": [],
  "summary": [],
  "grand_total": 0.0
}

def _extract_full_pdf_text(pdf_path: str) -> str:
    """Estrae il testo da TUTTE le pagine come unica stringa."""
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            log.info(f"Estrazione testo da {pdf_path}, {len(pdf.pages)} pagine.")
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    full_text += f"\n\n--- INIZIO PAGINA {i + 1} ---\n\n"
                    full_text += page_text
                else:
                    full_text += f"\n\n--- PAGINA {i + 1} (VUOTA) ---\n\n"
            return full_text
    except Exception as e:
        log.error(f"Errore durante l'estrazione del testo PDF: {e}")
        raise ValueError(f"Errore estrazione testo da PDF: {e}")

def _structure_text_with_ai(model, full_document_text: str) -> Dict[str, Any]:
    """Chiama l'IA per estrarre il computo metrico."""
    prompt = f"""
    Sei un assistente AI esperto in data entry di computi metrici.
    Analizza il 'TESTO DOCUMENTO COMPLETO' e riempi lo 'SCHEMA JSON'.

    ISTRUZIONI:
    1.  **metadata**: Estrai dalla Pagina 1. Cerca 'location' (luogo) e converti la data in 'YYYY-MM-DD'.
    2.  **bill_of_quantities**: Estrai da tutte le pagine.
    3.  **summary**: Estrai la tabella riassuntiva finale.
    4.  **grand_total**: Estrai il 'TOTALE OPERE' finale.
    5.  **_id**: Lascia questo campo vuoto.

    SCHEMA JSON (vuoto da compilare):
    ```json
    {json.dumps(TARGET_SCHEMA_EXTRACTION, indent=2)}
    ```

    TESTO DOCUMENTO COMPLETO:
    ---
    {full_document_text}
    ---

    Restituisci ESCLUSIVAMENTE il JSON compilato.
    """
    try:
        # Assumiamo che il 'model' sia il client GenAI
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        log.error(f"Errore chiamata API (Fase 1 Estrazione): {e}")
        try:
            log.debug(f"--- RISPOSTA GREZZA (DEBUG) ---\n{response.text}\n--------------------------")
        except:
            pass
        raise ValueError(f"Errore API AI: {e}")

def extract_computo_from_pdf(model, pdf_path: str, document_id: str) -> Dict[str, Any]:
    """
    Funzione principale della Fase 1 (Estrazione).
    Esegue l'estrazione del computo metrico dal PDF e restituisce un dizionario.
    """    
    full_text = _extract_full_pdf_text(pdf_path)
    if not full_text:
        log.warning("Nessun testo estratto da PDF. Interruzione.")
        return None

    structured_json = _structure_text_with_ai(model, full_text)
    
    if not structured_json:
        log.error("Errore nella Fase 1. Nessun JSON restituito dall'IA.")
        raise ValueError("Nessun JSON restituito dall'IA durante l'estrazione.")

    # Inserisce l'ID fornito prima di restituire i dati
    structured_json["_id"] = document_id
    
    log.info(f"Computo metrico estratto con successo: {document_id}")
    return structured_json

# --- Logica Cella 5: Generazione da Testo ---

# Schema che l'IA deve generare (senza metadata, aggiunti dopo)
SCHEMA_DA_GENERARE = {
  "bill_of_quantities": [
    {
      "category": "",
      "category_total": 0.0,
      "items": [
        {
          "reference": "", # Es. A.01.01
          "code": "",      # Es. E.P. 123
          "description": "",
          "unit": "",      # Es. mq, kg, cad
          "quantity": 0.0,
          "unit_price": 0.0,
          "item_total": 0.0
        }
      ]
    }
  ],
  "summary": [
      {
        "category": "",
        "price": 0.0
    }
  ],
  "grand_total": 0.0 
}

def generate_computo_from_description(model, project_description: str, metadata: Dict[str, Any], document_id: str) -> Dict[str, Any]:
    """
    Funzione principale della Fase 1 (Alternativa - Generazione).
    Genera un computo metrico stimato a partire da una descrizione.
    """
    prompt = f"""
    Sei un geometra e quantity surveyor esperto, specializzato nella creazione di preventivi e computi metrici estimativi (CME) per il mercato edile italiano.

    DESCRIZIONE DEL PROGETTO FORNITA DAL CLIENTE:
    "{project_description}"

    SCHEMA JSON DI OUTPUT (da riempire):
    ```json
    {json.dumps(SCHEMA_DA_GENERARE, indent=2)}
    ```

    IL TUO COMPITO:
    Basandoti *esclusivamente* sulla descrizione fornita, genera un Computo Metrico Estimativo (CME) realistico e dettagliato in formato JSON, conforme allo schema.

    ISTRUZIONI DETTAGLIATE:
    1.  **Inventa Voci Realistiche**: Identifica le lavorazioni necessarie (es. "Demolizione pavimento", "Posa piastrelle", "Traccia impianto elettrico") e raggruppale in `categories` logiche (es. "DEMOLIZIONI", "OPERE EDILI", "IMPIANTI").
    2.  **Stima Quantità e Prezzi**: Per ogni voce:
        -   Inventa un `reference` e un `code` fittizi.
        -   Scegli una `unit` (um) appropriata (mq, mc, cad, kg, ecc.).
        -   Stima una `quantity` (quantità) realistica basata sulla descrizione.
        -   Stima un `unit_price` (prezzo unitario) realistico in Euro, basato sul mercato italiano attuale.
        -   Calcola il `item_total` (quantity * unit_price).
    3.  **Calcola Totali**:
        -   Calcola il `category_total` per ogni categoria.
        -   Popola il `summary` con i totali di tutte le categorie.
        -   Calcola il `grand_total` (Totale Generale Lavori).
    4.  **Coerenza**: Assicurati che tutti i totali e sotto-totali siano matematicamente corretti.

    Restituisci ESCLUSIVAMENTE il JSON compilato, senza aggiungere commenti, 
    testo introduttivo o markdown '```json'.
    """
    try:
        response = model.generate_content(prompt)
        ai_generated_data = json.loads(response.text)

        # Uniamo i dati del "form" (metadata) con quelli generati dall'IA
        final_metric_data = {
            "_id": document_id,
            "metadata": metadata,
            "bill_of_quantities": ai_generated_data.get("bill_of_quantities", []),
            "summary": ai_generated_data.get("summary", []),
            "grand_total": ai_generated_data.get("grand_total", 0.0)
        }
        
        log.info(f"Computo metrico generato con successo: {document_id}")
        return final_metric_data
        
    except Exception as e:
        log.error(f"Errore chiamata API (Fase 1 Generazione): {e}")
        try:
            log.debug(f"--- RISPOSTA GREZZA (DEBUG) ---\n{response.text}\n--------------------------")
        except:
            pass
        raise ValueError(f"Errore API AI: {e}")

# --- Logica Cella 3: Pianificazione Lavori ---

def generate_work_pipeline(model, metric_data: Dict[str, Any], start_date: str) -> List[Dict[str, Any]]:
    """
    Funzione principale della Fase 2 (Pianificazione).
    Genera la pipeline dei lavori stimando tempi e operai.
    Restituisce una lista di lavori.
    """
    
    bill_of_quantities = metric_data.get("bill_of_quantities", [])
    
    work_item_schema = {
        "work_name": "Nome del lavoro (dalla descrizione)",
        "status": "planned",
        "start_date_planned": "YYYY-MM-DD",
        "end_date_planned": "YYYY-MM-DD",
        "start_date_actual": None,
        "end_date_actual": None,
        "duration_estimated_hours": 0,
        "duration_actual_hours": None,
        "number_of_workers": 0,
        "workers": []
    }
    
    prompt = f"""
    Sei un direttore dei lavori e project manager esperto nel settore edile.
    Ti fornisco il computo metrico di un progetto e una data di inizio lavori.

    DATA INIZIO LAVORI: {start_date}

    COMPUTO METRICO (JSON):
    {json.dumps(bill_of_quantities, indent=2)}

    SCHEMA DI OUTPUT (per ogni lavoro):
    {json.dumps(work_item_schema, indent=2)}

    IL TUO COMPITO:
    Genera una pipeline di lavori in formato JSON. La pipeline deve essere una lista di oggetti, ognuno conforme allo 'SCHEMA DI OUTPUT'.

    ISTRUZIONI DETTAGLIATE:
    1.  **Sequenza Logica**: Ordina i lavori in una sequenza costruttiva logica (es. prima DEMOLIZIONI).
    2.  **Stima Durata e Operai**: Stima 'duration_estimated_hours' e 'number_of_workers' per ogni voce.
    3.  **Pianificazione Date**:
        -   Parti dalla 'DATA INIZIO LAVORI'.
        -   Calcola 'start_date_planned' e 'end_date_planned' (formato 'YYYY-MM-DD').
        -   Assumi 8 ore/giorno, 5 giorni/settimana (Lun-Ven).
        -   I lavori sono in sequenza.
    4.  **Campi Fissi**: Imposta 'status' a 'planned' e i campi 'actual' a `null`.

    Restituisci ESCLUSIVAMENTE la lista JSON.
    """
    
    try:
        response = model.generate_content(prompt)
        work_pipeline = json.loads(response.text)
        
        if isinstance(work_pipeline, list):
            log.info(f"Pipeline lavori generata ({len(work_pipeline)} voci).")
            return work_pipeline
        else:
            log.error("Errore: L'IA non ha restituito una lista JSON per la pipeline.")
            log.debug(f"--- RISPOSTA GREZZA (DEBUG) ---\n{response.text}\n--------------------------")
            return None
    except Exception as e:
        log.error(f"Errore chiamata API (Fase 2 Pianificazione): {e}")
        try:
            log.debug(f"--- RISPOSTA GREZZA (DEBUG) ---\n{response.text}\n--------------------------")
        except:
            pass
        raise ValueError(f"Errore API AI: {e}")


# --- Logica Cella 7: Generazione PDF ---

def create_pdf_report(computo_data: Dict[str, Any], output_pdf_path: str):
    """
    Genera un PDF ReportLab basato sul JSON del computo metrico.
    """
    log.info(f"Inizio generazione PDF per: {output_pdf_path}")
    
    # === CARICA DATI ===
    data = computo_data
    meta = data.get("metadata", {})
    categories = data.get("bill_of_quantities", [])
    grand_total = data.get("grand_total", 0.0)

    # === STILI ===
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="FrontTitle", alignment=1, fontSize=20, leading=24, spaceAfter=20, textColor=colors.HexColor("#4B0082")))
    styles.add(ParagraphStyle(name="FrontSubTitle", alignment=1, fontSize=12, leading=16, spaceAfter=10))
    styles.add(ParagraphStyle(name="SectionTitle", fontSize=8, leading=10, textColor=colors.black, alignment=0))
    styles.add(ParagraphStyle(name="TableCell", fontSize=6, leading=7.5))
    styles.add(ParagraphStyle(name="Small", fontSize=8, leading=9))
    styles.add(ParagraphStyle(name="BoldRight", alignment=2, fontSize=9, textColor=colors.black))

    # === CREA DOCUMENTO ===
    doc = SimpleDocTemplate(output_pdf_path, pagesize=A4,
                            rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=20*mm, bottomMargin=15*mm)
    elements = []

    # ===========================
    # FRONTESPIZIO
    # ===========================
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("COMPUTO METRICO ESTIMATIVO", styles["FrontTitle"]))
    elements.append(Paragraph(meta.get("document_title", ""), styles["FrontSubTitle"]))
    elements.append(Spacer(1, 20))

    info_data = [
        ["Oggetto:", meta.get("subject", "")],
        ["Committente:", meta.get("client", "")],
        ["Luogo:", meta.get("location", "")],
        ["Data:", meta.get("date", "")],
        ["Responsabile tecnico:", meta.get("technician", "")],
    ]
    info_table = Table(info_data, colWidths=[120, 350])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EFE6FA")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#4B0082")),
        ("LINEBELOW", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 30))
    elements.append(PageBreak())

    # ===========================
    # TABELLA UNICA CON SEZIONI
    # ===========================
    data_table = [["Rif./Codice", "Descrizione", "U.M.", "Quantità", "Prezzo Unit.", "Totale (€)"]]

    for section in categories:
        data_table.append(["", "", "", "", "", ""])
        data_table.append([
            Paragraph(f"<b>{section.get('category', '')}</b>", styles["SectionTitle"]),
            "", "", "",
            "",
            f"{section.get('category_total', 0.0):,.2f}"
        ])
        
        for item in section.get("items", []):
            rif_code = f"{item.get('reference', '')} / {item.get('code', '')}"
            data_table.append([
                rif_code,
                Paragraph(item.get("description", ""), styles["TableCell"]),
                item.get("unit", ""),
                f"{item.get('quantity', 0):,.2f}",
                f"{item.get('unit_price', 0):,.2f}",
                f"{item.get('item_total', 0):,.2f}"
            ])

    table = Table(data_table, colWidths=[70, 230, 45, 40, 50, 55])
    table_style = TableStyle([
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EFE6FA")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#4B0082")),
        ("ALIGN", (3,1), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 6),
        ("ROWBACKGROUNDS", (0,2), (-1,-1), [colors.whitesmoke, colors.white]),
    ])

    for i, row in enumerate(data_table):
        if row[0] and "<b>" in str(row[0]):
            table_style.add("BACKGROUND", (0,i), (-1,i), colors.HexColor("#E7DAF8"))
            table_style.add("SPAN", (0,i), (3,i))
            table_style.add("ALIGN", (5,i), (5,i), "RIGHT")
            table_style.add("FONTSIZE", (0,i), (3,i), 7)
            table_style.add("FONTSIZE", (5,i), (5,i), 6)
            table_style.add("FONTNAME", (0,i), (-1,i), "Helvetica-Bold")
            table_style.add("TEXTCOLOR", (0,i), (3,i), colors.black)

    table.setStyle(table_style)
    elements.append(table)

    # ===========================
    # TABELLA RIEPILOGATIVA FINALE
    # ===========================
    summary_data = [["Descrizione", "Importo (€)"]]
    for section in categories:
        # FIX: Usa .get() per evitare KeyError se l'IA omette il campo
        cat_name = section.get("category", "Categoria Senza Nome")
        cat_total = section.get("category_total", 0.0)
        summary_data.append([cat_name, f"{cat_total:,.2f}"])
    summary_data.append(["TOTALE GENERALE", f"{grand_total:,.2f}"])
    summary_table = Table(summary_data, colWidths=[400, 100])
    summary_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EFE6FA")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#4B0082")),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))

    elements.append(Spacer(1, 20))
    elements.append(summary_table)

    # === CREA PDF ===
    try:
        doc.build(elements)
        log.info(f"PDF generato con successo: {output_pdf_path}")
    except Exception as e:
        log.error(f"Errore durante la creazione del PDF: {e}")
        raise ValueError(f"Errore ReportLab: {e}")