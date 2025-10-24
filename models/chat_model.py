# Chat and conversation management

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationalRetrievalChain
from typing import Dict, List

class ChatModel:
    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash", temperature: float = 0.3):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True
        )
        self.sessions = {}
    
    def get_or_create_memory(self, session_id: str) -> ConversationBufferMemory:
        """Get or create memory for a session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                output_key="answer"
            )
        return self.sessions[session_id]
    
    def clear_session(self, session_id: str):
        """Clear session memory"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def create_qa_chain(self, vector_store, session_id: str):
        """Create QA chain with retriever"""
        memory = self.get_or_create_memory(session_id)
        
        # Custom retriever
        class CustomRetriever:
            def __init__(self, vs):
                self.vector_store = vs
            
            def get_relevant_documents(self, query: str):
                results = self.vector_store.search(query, limit=4)
                
                class Doc:
                    def __init__(self, text, metadata):
                        self.page_content = text
                        self.metadata = metadata
                
                return [Doc(r["text"], r["metadata"]) for r in results]
        
        retriever = CustomRetriever(vector_store)
        
        chain = ConversationalRetrievalChain.from_llm(
            llm=self.llm,
            retriever=retriever,
            memory=memory,
            return_source_documents=True
        )
        
        return chain