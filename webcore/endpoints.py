from flask import Blueprint, render_template, request, jsonify

web_bp = Blueprint("web_bp", __name__)

@web_bp.route("/")
def index():
    return render_template("user_page.html")

@web_bp.route("/submit", methods=["POST"])
def handle_submit():
    user_data = request.json
    return jsonify({"status": "ok", "received": user_data})
