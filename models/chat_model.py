# Chat and conversation management

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from typing import Dict, List

class ChatModel:
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash", temperature: float = 0.3):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True
        )
        self.sessions = {}
    
    def get_or_create_history(self, session_id: str) -> ChatMessageHistory:
        """Get or create message history for a session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = ChatMessageHistory()
        return self.sessions[session_id]
    
    def clear_session(self, session_id: str):
        """Clear session history"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def chat(self, vector_store, session_id: str, question: str):
        """Chat with context from vector store"""
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.runnables import RunnablePassthrough
        
        # Get chat history
        history = self.get_or_create_history(session_id)
        
        # Search for relevant documents
        search_results = vector_store.search(question, limit=4)
        
        # Format context
        context = "\n\n".join([
            f"[Documento: {r['metadata']['source']}]\n{r['text']}"
            for r in search_results
        ])
        
        # Create prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Sei un assistente utile che risponde a domande basandoti sui documenti forniti.
            
Usa il seguente contesto per rispondere alla domanda. Se la risposta non è nel contesto, dillo chiaramente.

Contesto:
{context}"""),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])
        
        # Create chain
        chain = prompt | self.llm | StrOutputParser()
        
        # Get response
        response = chain.invoke({
            "context": context,
            "history": history.messages,
            "question": question
        })
        
        # Save to history
        history.add_user_message(question)
        history.add_ai_message(response)
        
        return {
            "answer": response,
            "source_documents": search_results
        }