from app import create_app
from dotenv import load_dotenv
import os

if __name__ == '__main__':
    load_dotenv()

    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    app = create_app()

    # 👇 Log di stato utili
    web_enabled = app.config.get("ENABLE_WEB_RETRIEVAL", False)
    print("Starting Flask RAG Application...")
    print(f"Server: http://{host}:{port}")
    print(f"Debug mode: {debug}")
    print(f"Web retrieval enabled: {web_enabled}")  # <-- utile

    app.run(host=host, port=port, debug=debug, use_reloader=False)