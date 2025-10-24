import os
import streamlit as st
import chromadb
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.docstore.document import Document
from dotenv import load_dotenv

# --- Setup ---
load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")

# Inizializza ChromaDB locale
PERSIST_DIR = "chroma_store"
client = chromadb.Client()
vectordb = Chroma(
    collection_name="documents",
    embedding_function=GoogleGenerativeAIEmbeddings(model="models/embedding-001"),
    persist_directory=PERSIST_DIR
)

# --- UI setup ---
st.set_page_config(page_title="Project assistant", layout="wide")
st.title("🧠 Project assistant")
st.caption("Chat con documenti caricati e memoria persistente (Gemini + ChromaDB)")

# --- Sidebar ---
with st.sidebar:
    st.header("📂 Documenti caricati")
    all_docs = vectordb._collection.get()["metadatas"]
    if all_docs:
        for i, doc in enumerate(all_docs):
            st.markdown(f"- {doc.get('source', f'Documento {i+1}')}")
    else:
        st.write("Nessun documento caricato ancora.")

    uploaded_files = st.file_uploader("Aggiungi documenti", accept_multiple_files=True, type=["txt", "md", "pdf"])

# --- Caricamento documenti ---
if uploaded_files:
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    for file in uploaded_files:
        file_content = file.read().decode("utf-8", errors="ignore")
        chunks = text_splitter.split_text(file_content)
        docs = [Document(page_content=chunk, metadata={"source": file.name}) for chunk in chunks]
        vectordb.add_documents(docs)
    vectordb.persist()
    st.sidebar.success("Documenti aggiunti con successo! Ricarica la pagina per aggiornarli.")

# --- Chat setup ---
if "messages" not in st.session_state:
    st.session_state["messages"] = []

chat_model = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.3)

retriever = vectordb.as_retriever(search_kwargs={"k": 3})
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

qa_chain = ConversationalRetrievalChain.from_llm(
    llm=chat_model,
    retriever=retriever,
    memory=memory
)

# --- Chat display ---
for msg in st.session_state["messages"]:
    role = "🧑‍💻" if msg["role"] == "user" else "🤖"
    st.chat_message(msg["role"]).markdown(f"{role} {msg['content']}")

# --- Input utente ---
user_input = st.chat_input("Scrivi un messaggio...")

if user_input:
    st.session_state["messages"].append({"role": "user", "content": user_input})
    st.chat_message("user").markdown(f"🧑‍💻 {user_input}")

    response = qa_chain({"question": user_input})
    answer = response["answer"]

    st.session_state["messages"].append({"role": "assistant", "content": answer})
    st.chat_message("assistant").markdown(f"🤖 {answer}")
