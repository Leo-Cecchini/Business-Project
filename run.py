from app import create_app
from dotenv import load_dotenv
import os

if __name__ == '__main__':
    # Carica le variabili dal file .env
    load_dotenv()

    # Legge la configurazione
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    # Crea l'app
    app = create_app()

    print(f"Starting Flask RAG Application...")
    print(f"Server: http://{host}:{port}")
    print(f"Debug mode: {debug}")

    # Avvia il server Flask sulla porta corretta
    app.run(host=host, port=port, debug=debug, use_reloader=False)

    """
    app = create_app()
    app.run(debug=False)
    
    # Get configuration from environment
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting Flask RAG Application...")
    print(f"Server: http://{host}:{port}")
    print(f"Debug mode: {debug}")
    
    app.run(host=host, port=port, debug=debug, use_reloader=False)
    """