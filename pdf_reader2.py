# ------imports------ #
import re
import PyPDF2
import unicodedata


# ------read pdf file------ #
def extract_info(pdf_path) -> str:
    """Extract text from a PDF file."""
    with open(pdf_path, "rb") as file:
        reader = PyPDF2.PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text


def normalize_persian(text: str) -> str:
    """Normalize Persian/Arabic text to canonical Unicode form.

    Fixes issues where PDF extraction produces Arabic Presentation Forms
    instead of standard Arabic/Persian characters.
    Also normalizes Arabic Yeh/Kaf/Alef Maksura to Persian standard forms.
    """
    if not text:
        return text

    # NFKC normalization decomposes presentation forms to standard characters
    text = unicodedata.normalize("NFKC", text)

    # Map Arabic variants to Persian standard forms
    text = text.replace("\u064a", "\u06cc")  # Arabic Yeh -> Persian Yeh
    text = text.replace("\u0643", "\u06a9")  # Arabic Kaf -> Persian Kaf
    text = text.replace("\u0649", "\u06cc")  # Arabic Alef Maksura -> Persian Yeh

    # Remove zero-width characters that can cause invisible mismatches
    text = text.replace("\u200c", " ")  # Zero-width non-joiner -> space
    text = text.replace("\u200d", "")  # Zero-width joiner -> remove
    text = text.replace("\u200b", "")  # Zero-width space -> remove
    text = text.replace("\ufeff", "")  # BOM -> remove

    # Collapse multiple spaces into one
    text = re.sub(r"\s+", " ", text).strip()

    return text


def extract_shomare_parvande(pdf_path: str) -> list:
    """Extract all شماره پرونده values from the PDF.

    In PDF-extracted RTL text, the number appears BEFORE the label, e.g.:
        140322920001653682 : شماره پرونده
    """
    try:
        raw_text = extract_info(pdf_path)
        text = normalize_persian(raw_text)

        # The number (15-20 digits) comes before the label in extracted RTL text
        pattern = r"(\d{15,20})\s*:?\s*\u0634\u0645\u0627\u0631\u0647\s+\u067e\u0631\u0648\u0646\u062f\u0647"
        matches = re.findall(pattern, text)

        # De-duplicate while preserving order
        seen = set()
        unique = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique
    except Exception:
        return []


def extract_client_number(text: str) -> str:
    """Extract client contract number (15-20 digits) from normalized text."""
    if not text:
        return None
    normalized_text = normalize_persian(text)

    # Pattern 1: number followed by : شماره قرارداد or شماره مشتری
    match = re.search(r"(\d{15,20})\s*:?\s*شماره\s*(?:قرارداد|مشتری)", normalized_text)
    if match:
        return match.group(1)

    # Pattern 2: number followed by - وکالت نامه به شماره
    match = re.search(r"(\d{15,20})\s*-\s*وکالت\s*نامه\s*به\s*شماره", normalized_text)
    if match:
        return match.group(1)

    # Pattern 3: وکالت نامه به شماره followed by number
    match = re.search(r"وکالت\s*نامه\s*به\s*شماره\s*(\d{15,20})", normalized_text)
    if match:
        return match.group(1)

    return None


def classify_document(text: str) -> str:
    """Classify the document type based on its text content.
    Returns: 'CONTRACT', 'DADKHAST', 'LAYEHE', or 'UNKNOWN'
    """
    if not text:
        return "UNKNOWN"

    normalized_text = normalize_persian(text)

    # Check for CONTRACT (قرارداد) - Must check this first as contracts can mention "لایحه" / "وکالت"
    if (
        "قرارداد الکترونیک وکالت" in normalized_text
        or "وکالت نامه و قرارداد الکترونیک" in normalized_text
    ):
        return "CONTRACT"

    # Check for LAYEHE (لایحه)
    if (
        "اعلام وکالت" in normalized_text
        or "لایحه خدمات قضایی" in normalized_text
        or "موضوع لایحه" in normalized_text
    ):
        return "LAYEHE"

    # Check for DADKHAST (دادخواست)
    if "دادخواست" in normalized_text:
        return "DADKHAST"

    return "UNKNOWN"


def check_layehe(pdf_path: str) -> str:
    """Check if the PDF is an اعلام وکالت/لایحه document.
    Restores compatibility with the frontend/backend status checking.
    """
    try:
        text = extract_info(pdf_path)
        doc_type = classify_document(text)
        if doc_type == "LAYEHE":
            return "it is اعلام وکالت"
    except Exception:
        pass
    return "unknown"
