# View routes

from flask import Blueprint, render_template

views_bp = Blueprint('views', __name__)

@views_bp.route('/')
def index():
    """Main page"""
    return render_template('index.html')