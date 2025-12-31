import { useState, useEffect, useRef } from 'react';
import { useSendProjectMessage } from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';

const STORAGE_KEY = 'site_chat_';

export default function SiteChat({ projectId }) {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const messagesEndRef = useRef(null);
    const sendMutation = useSendProjectMessage();

    useEffect(() => {
        try {
            const stored = localStorage.getItem(STORAGE_KEY + projectId);
            if (stored) {
                const parsed = JSON.parse(stored);
                setMessages(Array.isArray(parsed) ? parsed.slice(-200) : []);
            } else {
                setMessages([{ role: 'assistant', text: 'Chat del cantiere pronta.' }]);
            }
        } catch {
            setMessages([{ role: 'assistant', text: 'Chat del cantiere pronta.' }]);
        }
    }, [projectId]);

    useEffect(() => {
        if (messages.length > 0) {
            try {
                localStorage.setItem(
                    STORAGE_KEY + projectId,
                    JSON.stringify(messages.slice(-200))
                );
            } catch (error) {
                console.error('Error saving chat history:', error);
            }
        }
    }, [messages, projectId]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!input.trim() || sendMutation.isPending) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { role: 'user', text: userMessage }]);

        try {
            const response = await sendMutation.mutateAsync({
                projectId,
                message: userMessage,
            });

            setMessages(prev => [
                ...prev,
                {
                    role: 'assistant',
                    text: response.text || '(nessuna risposta)',
                    sources: response.sources || [],
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
        }
    };

    const handleReset = () => {
        setMessages([{ role: 'assistant', text: 'Chat del cantiere resettata.' }]);
        try {
            localStorage.removeItem(STORAGE_KEY + projectId);
        } catch { }
    };

    return (
        <Card>
            <div className="flex items-center justify-between mb-3">
                <div>
                    <h3 className="text-lg font-bold">💬 Chat Cantiere</h3>
                    <p className="text-xs text-[var(--muted)]">
                        Assistente AI per questo cantiere
                    </p>
                </div>
                <Button onClick={handleReset} disabled={sendMutation.isPending} className="text-xs !py-1 !px-2">
                    🔄 Reset
                </Button>
            </div>

            <div className="border border-[var(--border)] rounded-xl p-3 h-64 overflow-y-auto bg-[#fafafa] mb-3">
                {messages.map((msg, idx) => (
                    <div key={idx} className="mb-3 flex gap-2">
                        <div className="font-semibold text-xs text-[var(--muted)] min-w-[60px]">
                            {msg.role === 'user' ? 'Tu' : 'Assistant'}
                        </div>
                        <div className="flex-1">
                            <div
                                className={`inline-block px-3 py-2 rounded-2xl text-sm max-w-full break-words ${msg.role === 'user'
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-gray-200 text-gray-900'
                                    }`}
                            >
                                {msg.text}
                            </div>
                            {msg.sources && msg.sources.length > 0 && (
                                <div className="mt-2 text-xs text-[var(--muted)]">
                                    <strong>Fonti:</strong>
                                    {msg.sources.slice(0, 3).map((s, i) => (
                                        <div key={i}>
                                            [{i + 1}] {s.title || s.source || 'Fonte'}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                {sendMutation.isPending && (
                    <div className="mb-3 flex gap-2">
                        <div className="font-semibold text-xs text-[var(--muted)] min-w-[60px]">
                            Assistant
                        </div>
                        <div className="text-sm text-[var(--muted)] animate-pulse">
                            Sto pensando...
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            <form onSubmit={handleSubmit} className="flex gap-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Scrivi un messaggio..."
                    className="flex-1 px-3 py-2 border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
                    disabled={sendMutation.isPending}
                />
                <Button type="submit" variant="primary" disabled={sendMutation.isPending}>
                    Invia
                </Button>
            </form>
        </Card>
    );
}