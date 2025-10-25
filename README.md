# Flask RAG Application with Qdrant

A production-ready Retrieval-Augmented Generation (RAG) chatbot built with Flask, Qdrant vector database, and Google's Gemini AI.

## Features

- 📄 **Multi-format document support**: PDF, TXT, MD
- 🔍 **Semantic search** with Qdrant vector database
- 💬 **Conversational memory** per session
- 🎨 **Clean, responsive UI** with vanilla JavaScript
- 🔒 **Session-based chat isolation**
- ⚡ **Fast and scalable** architecture

## Project Structure

```
project/
├── app.py                  # Flask application factory
├── config.py              # Configuration settings
├── run.py                 # Application entry point
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── models/
│   ├── vector_store.py   # Qdrant vector store management
│   └── chat_model.py     # LLM and conversation management
├── routes/
│   ├── api.py            # API endpoints
│   └── views.py          # View routes
├── utils/
│   └── file_processor.py # File processing utilities
├── templates/
│   └── index.html        # Main HTML template
└── static/
    ├── css/
    │   └── style.css     # Styles
    └── js/
        └── app.js        # Frontend JavaScript
```

## Installation

### 1. Install Python dependencies

```bash
# 1. Create virtual environment
# With venv
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# or With conda
conda create -n env_name python=3.12
conda activate env_name

# 2. Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your Google API key
# Get key from: https://makersuite.google.com/app/apikey
```

### 3. Run the application

```bash
python run.py
```

Qdrant will automatically create a local `qdrant_data/` folder for storage.

Open your browser at: http://localhost:5000

## API Endpoints

### Upload Documents
```http
POST /api/upload
Content-Type: multipart/form-data

files: [file1, file2, ...]
```

### Chat
```http
POST /api/chat
Content-Type: application/json

{
  "question": "Your question here"
}
```

### Get Documents
```http
GET /api/documents
```

### Reset Chat
```http
POST /api/reset-chat
```

### Reset Database
```http
POST /api/reset-db
```

## Configuration

Edit `config.py` or use environment variables:

- `GOOGLE_API_KEY`: Your Google AI API key (required)
- `QDRANT_PATH`: Local folder for Qdrant storage (default: ./qdrant_data)
- `CHUNK_SIZE`: Text chunk size (default: 1000)
- `CHUNK_OVERLAP`: Chunk overlap (default: 200)
- `SEARCH_LIMIT`: Number of documents to retrieve (default: 4)

## Development

### Running in debug mode

```bash
export FLASK_DEBUG=True
python run.py
```

### Adding new features

1. **New API endpoint**: Add to `routes/api.py`
2. **New model**: Create in `models/`
3. **New utility**: Create in `utils/`
4. **Frontend changes**: Edit `static/js/app.js` or `static/css/style.css`

## Production Deployment

### Using Gunicorn

```bash
pip install gunicorn

gunicorn -w 4 -b 0.0.0.0:5000 'app:create_app()'
```

### Using Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:create_app()"]
```

## Troubleshooting

**Qdrant storage error:**
- Check write permissions for `qdrant_data/` folder
- Delete `qdrant_data/` folder and restart to reset database

**Google API error:**
- Verify API key is correct
- Check API quota at Google AI Studio

**File upload fails:**
- Check file size (max 16MB)
- Verify file format is supported

## License

MIT License
"""