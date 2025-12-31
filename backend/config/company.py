# config/company.py
"""Company configuration - single company mode."""
import os

COMPANY_INFO = {
    "name": os.getenv("COMPANY_NAME", "Edil S.r.l."),
    "vat_number": os.getenv("COMPANY_VAT", "IT12345678901"),
    "address": os.getenv("COMPANY_ADDRESS", ""),
    "city": os.getenv("COMPANY_CITY", ""),
    "country": os.getenv("COMPANY_COUNTRY", "Italia"),
    "phone": os.getenv("COMPANY_PHONE", ""),
    "email": os.getenv("COMPANY_EMAIL", ""),
}

def get_company_info():
    """Returns company info dict."""
    return COMPANY_INFO.copy()