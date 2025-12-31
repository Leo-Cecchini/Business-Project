import { useState } from 'react';
import Card from '../ui/Card';
import Button from '../ui/Button';

export default function CompanyChat() {
    const [messages, setMessages] = useState([
        { role: 'assistant', text: 'Benvenuto! Chat generale dell\'azienda.' }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { role: 'user', text: userMessage }]);
        setLoading(true);

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMessage }),
            });

            const data = await response.json();
            const reply = data.reply || data.answer || data.text || 'OK';

            setMessages(prev => [
                ...prev,
                {
                    role: 'assistant',
                    text: reply,
                    sources: data.sources || [],
                },
            ]);
        } catch (error) {
            setMessages(prev => [
                ...prev,
                {
                    role: 'assistant',
                    text: `Errore: ${error.message}`,
                },
            ]);
        } finally {
            setLoading(false);
        }
    };

    const handleReset = () => {
        setMessages([
            { role: 'assistant', text: 'Chat resettata. Come posso aiutarti?' }
        ]);
    };

    return (
        <Card>
            <h3 className="text-lg font-bold mb-1">Chat (Azienda)</h3>
            <p className="text-xs text-[var(--muted)] mb-3">Contesto: azienda</p>

            <div className="border border-[var(--border)] rounded-xl p-3 h-64 overflow-y-auto bg-[#fafafa] mb-3">
                {messages.map((msg, idx) => (
                    <div key={idx} className="mb-3 flex gap-2">
                        <div className="font-semibold text-xs text-[var(--muted)] min-w-[60px]">
                            {msg.role === 'user' ? 'Tu' : 'Assistant'}
                        </div>
                        <div className="flex-1">
                            <div className={`inline-block px-3 py-2 rounded-2xl text-sm ${msg.role === 'user'
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-gray-200 text-gray-900'
                                }`}>
                                {msg.text}
                            </div>
                            {msg.sources && msg.sources.length > 0 && (
                                <div className="mt-2 text-xs text-[var(--muted)]">
                                    <strong>Fonti:</strong>
                                    {msg.sources.map((s, i) => (
                                        <div key={i}>
                                            [{i + 1}] {s.title || s.source || 'Fonte'}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                {loading && (
                    <div className="mb-3 flex gap-2">
                        <div className="font-semibold text-xs text-[var(--muted)] min-w-[60px]">
                            Assistant
                        </div>
                        <div className="text-sm text-[var(--muted)] animate-pulse">
                            Sto pensando...
                        </div>
                    </div>
                )}
            </div>

            <form onSubmit={handleSubmit} className="flex gap-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Scrivi un messaggio..."
                    className="flex-1 px-3 py-2 border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
                    disabled={loading}
                />
                <Button type="button" onClick={handleReset} disabled={loading}>
                    Reset
                </Button>
                <Button type="submit" variant="primary" disabled={loading}>
                    Invia
                </Button>
            </form>
        </Card>
    );
}