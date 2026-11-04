"""
extract info from pdf file (contract)


"""

# ------imports------#
import re
import PyPDF2
import unicodedata


# ------read pdf file------#
def extract_info(pdf_path) -> str:
    """Extract text from a PDF file."""
    with open(pdf_path, "rb") as file:
        reader = PyPDF2.PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text


# ------find text------#
def find_text(pdf_path1):
    """Find specific information in the extracted text."""
    text = extract_info(pdf_path1)

    # Normalize the entire text once
    norm_text = unicodedata.normalize("NFKC", text)
    norm_text = norm_text.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    norm_text = (
        norm_text.replace("\u200c", " ")
        .replace("\u200d", "")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )

    result = {}

    # شماره قرارداد
    shomare_ghrardad = re.search(r"شماره قرارداد\s*[:\-]?\s*(\d{15,20})", norm_text)
    if not shomare_ghrardad:
        shomare_ghrardad = re.search(
            r"(\d{15,20})\s*.*?[:\-]?\s*شماره قرارداد", norm_text
        )
    if shomare_ghrardad:
        result["client_number"] = shomare_ghrardad.group(1)

    # تاریخ تنظیم
    tarikh_tanzim = re.search(r"تاریخ تنظیم\s*[:\-]?\s*(\d{4}/\d{2}/\d{2})", norm_text)
    if not tarikh_tanzim:
        tarikh_tanzim = re.search(
            r"(\d{4}/\d{2}/\d{2})\s*.*?[:\-]?\s*تاریخ تنظیم", norm_text
        )
    if tarikh_tanzim:
        result["contract_date"] = tarikh_tanzim.group(1)

    # Check if text is extracted as reversed RTL (common with PyPDF2 for Persian)
    # In reversed RTL, ID number will appear BEFORE "شماره ملی"
    is_reversed_rtl = bool(re.search(r"\d{10}\s*:\s*شماره ملی", norm_text))

    if is_reversed_rtl:
        # 1. First Name (Everything up to "نام :")
        fn_matches = re.findall(
            r"(?:^|\s)([^\s:\n]+(?:[ \t]+[^\s:\n]+)*)\s*نام\s*:", norm_text
        )
        if len(fn_matches) > 1:
            result["first_name"] = fn_matches[1].strip()
        elif len(fn_matches) == 1:
            result["first_name"] = fn_matches[0].strip()

        # 2. Last Name (Between "نام :" and "نام خانوادگی :")
        ln_matches = re.findall(r"نام\s*:\s*(.*?)\s*نام خانوادگی\s*:", norm_text)
        if len(ln_matches) > 1:
            result["last_name"] = ln_matches[1].strip()
        elif len(ln_matches) == 1:
            result["last_name"] = ln_matches[0].strip()

        # 3. Father Name (Between "نام خانوادگی :" and "نام پدر :")
        fan_matches = re.findall(r"نام خانوادگی\s*:\s*(.*?)\s*نام پدر\s*:", norm_text)
        if len(fan_matches) > 1:
            result["fathername"] = fan_matches[1].strip()
        elif len(fan_matches) == 1:
            result["fathername"] = fan_matches[0].strip()

        # 4. ID Number (Before "شماره ملی")
        id_matches = re.findall(r"(\d{10})\s*:\s*شماره ملی", norm_text)
        if len(id_matches) > 1:
            result["id_number"] = id_matches[1].strip()
        elif len(id_matches) == 1:
            result["id_number"] = id_matches[0].strip()
    else:
        # Normal LTR format
        # 1. First Name
        fn_matches = re.findall(r"نام\s*:\s*(.*?)\s*نام خانوادگی\s*:", norm_text)
        if len(fn_matches) > 1:
            result["first_name"] = fn_matches[1].strip()
        elif len(fn_matches) == 1:
            result["first_name"] = fn_matches[0].strip()

        # 2. Last Name
        ln_matches = re.findall(r"نام خانوادگی\s*:\s*(.*?)\s*نام پدر\s*:", norm_text)
        if len(ln_matches) > 1:
            result["last_name"] = ln_matches[1].strip()
        elif len(ln_matches) == 1:
            result["last_name"] = ln_matches[0].strip()

        # 3. Father Name
        fan_matches = re.findall(r"نام پدر\s*:\s*(.*?)\s*شماره ملی\s*:", norm_text)
        if len(fan_matches) > 1:
            result["fathername"] = fan_matches[1].strip()
        elif len(fan_matches) == 1:
            result["fathername"] = fan_matches[0].strip()

        # 4. ID Number
        id_matches = re.findall(r"شماره ملی\s*:\s*(\d{10})", norm_text)
        if len(id_matches) > 1:
            result["id_number"] = id_matches[1].strip()
        elif len(id_matches) == 1:
            result["id_number"] = id_matches[0].strip()

    # قرارداد ضمیمه
    ghrardad_zamime = re.search(r"وکالت\s*نامه\s*به\s*شماره\s*(\d{15,20})", norm_text)
    if not ghrardad_zamime:
        ghrardad_zamime = re.search(
            r"(\d{15,20})\s*-\s*وکالت\s*نامه\s*به\s*شماره", norm_text
        )
    if ghrardad_zamime:
        result["ghrardad_zamime"] = ghrardad_zamime.group(1)

    # مبلغ قرارداد
    amount_match = re.search(
        r"مبلغ\s*قرارداد.{0,100}?([\d,]+)\s*ریال", norm_text, re.DOTALL
    )
    if not amount_match:
        # PDF extraction sometimes reverses RTL order: ریال appears before the number
        amount_match = re.search(
            r"مبلغ\s*قرارداد\s*ریال\s*([\d,]+)", norm_text, re.DOTALL
        )
    if amount_match:
        result["contract_amount"] = amount_match.group(1).strip()

    return result if result else None


# ------run app------#
def run_pdf(pdf_path: str):
    """Run the PDF extraction and information finding process."""
    info = find_text(pdf_path)
    return info
