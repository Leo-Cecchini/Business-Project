# routes/company.py
from flask import Blueprint, jsonify, request
from services import CompanyService

company_bp = Blueprint('company', __name__, url_prefix='/api/company')

@company_bp.route('/overview', methods=['GET'])
def company_overview():
    """Ritorna KPI e info generali per la dashboard."""
    try:
        data = CompanyService.get_overview()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@company_bp.route('/dashboard/summary', methods=['GET'])
def dashboard_summary():
    """Alias per company_overview - compatibilità frontend."""
    return company_overview()

@company_bp.route('/documents', methods=['GET'])
def list_company_documents():
    """Lista documenti corporate."""
    try:
        docs = CompanyService.list_documents()
        return jsonify({"documents": docs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@company_bp.route('/documents', methods=['POST'])
def upload_company_document():
    """Upload e indicizzazione documento corporate."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    try:
        result = CompanyService.upload_document(file)
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500