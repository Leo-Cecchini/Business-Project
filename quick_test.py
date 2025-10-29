import os
from langchain_google_genai import ChatGoogleGenerativeAI

# opzionale: prendi il modello dall'env, altrimenti usa 2.5
model = os.getenv("MODEL_NAME", "gemini-2.5-flash")

llm = ChatGoogleGenerativeAI(
    model=model,
    temperature=0,
    convert_system_message_to_human=True
)

print(llm.invoke("Rispondi solo con: ok").content)