# File processing utilities

import PyPDF2
from io import BytesIO
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import List, Tuple

class FileProcessor:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
    
    def extract_text_from_pdf(self, file_data: bytes) -> str:
        """Extract text from PDF"""
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(file_data))
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            raise ValueError(f"Error reading PDF: {str(e)}")
    
    def process_file(self, file_data: bytes, filename: str) -> Tuple[List[str], List[dict]]:
        """Process uploaded file and return chunks with metadata"""
        # Extract text based on file extension
        if filename.lower().endswith('.pdf'):
            text = self.extract_text_from_pdf(file_data)
        else:
            text = file_data.decode('utf-8', errors='ignore')
        
        if not text.strip():
            raise ValueError("File is empty")
        
        # Split into chunks
        chunks = self.text_splitter.split_text(text)
        
        # Create metadata for each chunk
        metadatas = [
            {
                "source": filename,
                "chunk_id": i
            }
            for i in range(len(chunks))
        ]
        
        return chunks, metadatas