from flask import Flask

def create_web():
    app = Flask(__name__)
    from .endpoints import web_bp
    app.register_blueprint(web_bp)
    return app
