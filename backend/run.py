from app import create_app
from dotenv import load_dotenv
import os
import logging

if __name__ == '__main__':
    load_dotenv()

    # ✅ Controllo chiave e modello
    logging.basicConfig(level=logging.INFO)
    logging.info("GOOGLE_API_KEY presente: %s", bool(os.getenv("GOOGLE_API_KEY")))
    logging.info("MODEL_NAME: %s", os.getenv("MODEL_NAME"))

    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    app = create_app()

    # 👇 Log di stato utili
    web_enabled = app.config.get("ENABLE_WEB_RETRIEVAL", False)
    print("Starting Flask RAG Application...")
    print(f"Server: http://{host}:{port}")
    print(f"Debug mode: {debug}")
    print(f"Web retrieval enabled: {web_enabled}")

    app.run(host=host, port=port, debug=debug, use_reloader=False)