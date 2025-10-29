import os
import io
import streamlit as st
import chromadb
from dotenv import load_dotenv

from PyPDF2 import PdfReader

from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.docstore.document import Document

# =========================
# Bootstrap & configuration
# =========================
load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY") or ""
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash")

st.set_page_config(page_title="Project assistant", layout="wide")
st.title("🧠 Project assistant")
st.caption("Chat con documenti caricati e memoria persistente (Gemini + ChromaDB)")

# =========================
# Helper: robust file reading
# =========================
def read_file_to_text(uploaded_file) -> str:
  name = (uploaded_file.name or "").lower()
  if name.endswith(".pdf"):
    try:
      # PyPDF2 expects a file-like object; Streamlit provides one already
      pdf_bytes = uploaded_file.read()
      uploaded_file.seek(0)  # reset pointer for potential future reads
      reader = PdfReader(io.BytesIO(pdf_bytes))
      pages = []
      for page in reader.pages:
        try:
          pages.append(page.extract_text() or "")
        except Exception:
          pages.append("")
      return "\n".join(pages)
    except Exception:
      return ""
  # Fallback: treat as text
  try:
    content = uploaded_file.read()
    uploaded_file.seek(0)
    return content.decode("utf-8", errors="ignore")
  except Exception:
    return ""

# =========================
# Cache heavy resources
# =========================
@st.cache_resource(show_spinner=False)
def get_embeddings():
  return GoogleGenerativeAIEmbeddings(model="models/embedding-001")

@st.cache_resource(show_spinner=False)
def get_vectordb(persist_dir: str):
  # Use PersistentClient to ensure on-disk storage is always consistent
  client = chromadb.PersistentClient(path=persist_dir)
  return Chroma(
    collection_name="documents",
    embedding_function=get_embeddings(),
    persist_directory=persist_dir,
    client=client,
  )

@st.cache_resource(show_spinner=False)
def get_llm(model_name: str):
  return ChatGoogleGenerativeAI(
    model=model_name,
    temperature=0.3,
    convert_system_message_to_human=True,
  )

# Paths / stores
PERSIST_DIR = "chroma_store"
vectordb = get_vectordb(PERSIST_DIR)
llm = get_llm(MODEL_NAME)

# =========================
# Sidebar UI
# =========================
with st.sidebar:
  st.header("📂 Documenti caricati")
  # Avoid relying on private API; show count instead (safe across versions)
  try:
    doc_count = vectordb._collection.count()  # still private, but stable; wrap in try
  except Exception:
    doc_count = None

  if doc_count:
    st.write(f"{doc_count} documenti indicizzati.")
  else:
    st.write("Nessun documento indicizzato.")

  uploaded_files = st.file_uploader(
    "Aggiungi documenti",
    accept_multiple_files=True,
    type=["txt", "md", "pdf"]
  )

# =========================
# Ingest documents
# =========================
if uploaded_files:
  text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
  added_any = False
  for file in uploaded_files:
    text = read_file_to_text(file)
    if not text.strip():
      continue
    chunks = text_splitter.split_text(text)
    docs = [Document(page_content=chunk, metadata={"source": file.name}) for chunk in chunks]
    try:
      vectordb.add_documents(docs)
      added_any = True
    except Exception as e:
      st.sidebar.error(f"Errore durante l'ingest di {file.name}: {e}")
  if added_any:
    vectordb.persist()
    st.sidebar.success("Documenti aggiunti con successo! Ricarica la pagina per aggiornarli.")

# =========================
# Chat setup
# =========================
if "messages" not in st.session_state:
  st.session_state["messages"] = []

retriever = vectordb.as_retriever(search_kwargs={"k": 3})
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

qa_chain = ConversationalRetrievalChain.from_llm(
  llm=llm,
  retriever=retriever,
  memory=memory
)

# =========================
# Render history
# =========================
for msg in st.session_state["messages"]:
  role = "🧑‍💻" if msg["role"] == "user" else "🤖"
  st.chat_message(msg["role"]).markdown(f"{role} {msg['content']}")

# =========================
# Input & response
# =========================
user_input = st.chat_input("Scrivi un messaggio...")

if user_input:
  st.session_state["messages"].append({"role": "user", "content": user_input})
  st.chat_message("user").markdown(f"🧑‍💻 {user_input}")

  # If DB is empty, gracefully fall back to plain LLM
  try:
    with st.spinner("Sto pensando..."):
      try:
        has_docs = vectordb._collection.count() > 0
      except Exception:
        has_docs = False

      if has_docs:
        response = qa_chain({"question": user_input})
        answer = response.get("answer") or ""
      else:
        # No vectors yet: answer directly without retrieval
        res = llm.invoke(user_input)
        answer = getattr(res, "content", str(res))
  except Exception as e:
    st.error(f"Errore durante la risposta: {e}")
    answer = "Si è verificato un errore durante l'elaborazione della risposta."

  st.session_state["messages"].append({"role": "assistant", "content": answer})
  st.chat_message("assistant").markdown(f"🤖 {answer}")
