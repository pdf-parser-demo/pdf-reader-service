from fastapi import FastAPI, UploadFile, File
from pdf2image import convert_from_path
import pytesseract
import shutil
import os

app = FastAPI()

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.get("/hola")
def home():
    return {"message": "OCR listo maestro"}

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    #valida que sea PDF
    if not file.filename.endswith(".pdf"):
        return {"error": "Solo se admiten archivos PDF"}

    #crea ruta para guardado
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    #guarda archivo en el disco
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    #convierte PDF a imágenes
    images = pdf_to_images(file_path)

    #OCR por imágen
    extracted_text = []
    #OCR para recursivo
    for idx, image in enumerate(images):
        text = pytesseract.image_to_string(image, lang="spa+eng")
        extracted_text.append({
            "page": idx+1,
            "text": text
        })

    #une todo el OCR para tratarlo como un bloque completo
    full_text = "\n".join(page["text"] for page in extracted_text)

    document = parse_document(full_text)
    # invoice_blocks = split_invoices(full_text)

    # documents = []
    # for block in invoice_blocks:
    #     documents.append(parse_document(block))

    return {
        "status": "ok",
        "message": "Proceso completado",
        "documents": [document],
        "pages": extracted_text
    }

#convierte PDF en una lista de imágenes PIL
def pdf_to_images(pdf_path):
    images = convert_from_path(pdf_path, dpi=200)
    return images

#normalización del texto, eliminación de ruido y tratamiento por bloque
def normalize_text(text: str) -> list[str]:
    text = text.upper()
    text = text.replace("\r", "")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return lines

#Extracción de encabezados
def extract_headers(lines: list[str]) -> dict:
    data = {
        "invoice": {},
        "bill_to": {},
        "ship_to": {},
        "total": None
    }

    i = 0
    while i < len(lines):
        line = lines[i]

        # Invoice number
        if "INVOICE #" in line:
            data["invoice"]["number"] = line.split("#")[-1].strip()

        # Invoice date
        if "INVOICE DATE" in line:
            data["invoice"]["date"] = line.replace("INVOICE DATE", "").strip()

        # Due date
        if "DUE DATE" in line:
            data["invoice"]["due_date"] = line.replace("DUE DATE", "").strip()

        # PO number
        if "P.O.#" in line or "PO#" in line:
            data["invoice"]["po_number"] = line.split("#")[-1].strip()

        # Bill To (bloque)
        if line == "BILL TO":
            name = lines[i + 1] if i + 1 < len(lines) else None
            data["bill_to"]["name"] = name

        # Ship To (bloque)
        if line == "SHIP TO":
            address_lines = []
            j = i + 1
            while j < len(lines) and not any(
                k in lines[j] for k in ["INVOICE", "QTY", "TOTAL"]
            ):
                address_lines.append(lines[j])
                j += 1
            data["ship_to"]["address"] = " ".join(address_lines)

        # Total
        if line.startswith("TOTAL"):
            value = line.replace("TOTAL", "").replace("$", "").strip()
            data["total"] = float(value)

        i += 1

    return data

#Reconstrucción de tablas
def extract_items(lines: list[str]) -> list[dict]:
    table_lines = []
    in_table = False

    for line in lines:
        if "QTY" in line or "DESCRIPTION" in line:
            in_table = True
            continue

        if in_table and line.startswith("TOTAL"):
            break

        if in_table:
            table_lines.append(line)

    descriptions = []
    prices = []

    for line in table_lines:
        # líneas tipo: "1000 ROSES"
        if any(c.isalpha() for c in line) and any(c.isdigit() for c in line):
            parts = line.split(" ", 1)
            if parts[0].isdigit():
                descriptions.append({
                    "qty": int(parts[0]),
                    "description": parts[1].strip()
                })

        # líneas tipo: "0.20 200.00"
        elif line.count(".") >= 2:
            p = line.split()
            prices.append({
                "unit_price": float(p[0]),
                "amount": float(p[1])
            })

    items = []
    count = min(len(descriptions), len(prices))

    for i in range(count):
        items.append({
            "qty": descriptions[i]["qty"],
            "description": descriptions[i]["description"],
            "unit_price": prices[i]["unit_price"],
            "amount": prices[i]["amount"]
        })

    return items

#ensamblaje
def parse_document(ocr_text: str) -> dict:
    lines = normalize_text(ocr_text)

    headers = extract_headers(lines)
    items = extract_items(lines)

    return {
        "invoice": headers["invoice"],
        "bill_to": headers["bill_to"],
        "ship_to": headers["ship_to"],
        "items": items,
        "total": headers["total"],
        "currency": "USD"
    }

#separa el texto en facturas para tratamiento recursivo
def split_invoices(full_text: str) -> list[str]:
    text = full_text.upper()
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    invoices = []
    current_invoice = []
    in_invoice = False

    for line in lines:
        if "INVOICE" in line or "FACTURA" in line:
            if current_invoice:
                invoices.append("\n".join(current_invoice))
                current_invoice = []
            in_invoice = True

        if in_invoice:
            current_invoice.append(line)

        if in_invoice and line.startswith("TOTAL"):
            invoices.append("\n".join(current_invoice))
            current_invoice = []
            in_invoice = False

    return invoices
