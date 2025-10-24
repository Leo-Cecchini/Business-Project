class ChatApp {
    constructor() {
        this.messagesContainer = document.getElementById('messagesContainer');
        this.messageInput = document.getElementById('messageInput');
        this.chatForm = document.getElementById('chatForm');
        this.fileInput = document.getElementById('fileInput');
        this.documentsList = document.getElementById('documentsList');
        this.resetChatBtn = document.getElementById('resetChatBtn');
        this.resetDbBtn = document.getElementById('resetDbBtn');
        
        this.init();
    }
    
    init() {
        // Event listeners
        this.chatForm.addEventListener('submit', (e) => this.handleSubmit(e));
        this.fileInput.addEventListener('change', (e) => this.handleFileUpload(e));
        this.resetChatBtn.addEventListener('click', () => this.resetChat());
        this.resetDbBtn.addEventListener('click', () => this.resetDatabase());
        
        // Load documents on start
        this.loadDocuments();
    }
    
    async handleSubmit(e) {
        e.preventDefault();
        
        const message = this.messageInput.value.trim();
        if (!message) return;
        
        // Add user message
        this.addMessage('user', message);
        this.messageInput.value = '';
        
        // Show loading
        const loadingId = this.addLoadingMessage();
        
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: message })
            });
            
            const data = await response.json();
            
            // Remove loading
            this.removeMessage(loadingId);
            
            if (response.ok) {
                this.addMessage('assistant', data.answer, data.sources);
            } else {
                this.addMessage('assistant', `Errore: ${data.error}`);
            }
            
        } catch (error) {
            this.removeMessage(loadingId);
            this.addMessage('assistant', `Errore di connessione: ${error.message}`);
        }
    }
    
    async handleFileUpload(e) {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;
        
        const formData = new FormData();
        files.forEach(file => formData.append('files', file));
        
        // Disable upload during processing
        this.fileInput.disabled = true;
        this.addMessage('assistant', '📤 Caricamento file in corso...');
        
        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (response.ok) {
                let message = `✅ ${data.processed} file caricati con successo!`;
                if (data.errors.length > 0) {
                    message += `\n\nErrori:\n${data.errors.join('\n')}`;
                }
                this.addMessage('assistant', message);
                this.loadDocuments();
            } else {
                this.addMessage('assistant', `❌ Errore: ${data.error}`);
            }
            
        } catch (error) {
            this.addMessage('assistant', `❌ Errore di caricamento: ${error.message}`);
        } finally {
            this.fileInput.disabled = false;
            this.fileInput.value = '';
        }
    }
    
    async loadDocuments() {
        try {
            const response = await fetch('/api/documents');
            const data = await response.json();
            
            if (data.documents.length === 0) {
                this.documentsList.innerHTML = '<p class="no-docs">Nessun documento caricato</p>';
            } else {
                this.documentsList.innerHTML = data.documents
                    .map(doc => `<div class="doc-item">📄 ${doc.source}</div>`)
                    .join('');
            }
        } catch (error) {
            console.error('Error loading documents:', error);
        }
    }
    
    async resetChat() {
        if (!confirm('Vuoi resettare la cronologia chat?')) return;
        
        try {
            await fetch('/api/reset-chat', { method: 'POST' });
            this.messagesContainer.innerHTML = `
                <div class="message assistant">
                    <div class="message-content">
                        <strong>🤖 Assistant:</strong>
                        <p>Chat resettata. Come posso aiutarti?</p>
                    </div>
                </div>
            `;
        } catch (error) {
            alert('Errore durante il reset della chat');
        }
    }
    
    async resetDatabase() {
        if (!confirm('Vuoi eliminare tutti i documenti? Questa azione è irreversibile!')) return;
        
        try {
            const response = await fetch('/api/reset-db', { method: 'POST' });
            const data = await response.json();
            
            if (response.ok) {
                alert('✅ Database resettato con successo!');
                this.loadDocuments();
            } else {
                alert(`❌ Errore: ${data.error}`);
            }
        } catch (error) {
            alert('Errore durante il reset del database');
        }
    }
    
    addMessage(role, content, sources = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        messageDiv.id = `msg-${Date.now()}`;
        
        let sourcesHtml = '';
        if (sources && sources.length > 0) {
            sourcesHtml = `
                <div class="sources">
                    <h4>📚 Fonti utilizzate:</h4>
                    ${sources.map((src, i) => `
                        <div class="source-item">
                            <strong>${i + 1}. ${src.source}</strong>
                            <p>${src.text}</p>
                        </div>
                    `).join('')}
                </div>
            `;
        }
        
        const icon = role === 'user' ? '🧑‍💻' : '🤖';
        const label = role === 'user' ? 'Tu' : 'Assistant';
        
        messageDiv.innerHTML = `
            <div class="message-content">
                <strong>${icon} ${label}:</strong>
                <p>${this.escapeHtml(content)}</p>
                ${sourcesHtml}
            </div>
        `;
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
        
        return messageDiv.id;
    }
    
    addLoadingMessage() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        messageDiv.id = `loading-${Date.now()}`;
        
        messageDiv.innerHTML = `
            <div class="message-content">
                <strong>🤖 Assistant:</strong>
                <p><span class="loading"></span> Sto pensando...</p>
            </div>
        `;
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
        
        return messageDiv.id;
    }
    
    removeMessage(messageId) {
        const element = document.getElementById(messageId);
        if (element) element.remove();
    }
    
    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new ChatApp();
});