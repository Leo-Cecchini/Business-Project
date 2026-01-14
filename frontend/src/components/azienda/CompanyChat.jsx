import { useEffect, useMemo, useRef, useState } from 'react';
import Card from '../ui/Card';
import Button from '../ui/Button';

function formatEuro(n) {
    const x = Number(n || 0);
    return x.toLocaleString('it-IT', { style: 'currency', currency: 'EUR' });
}

function safeNum(n) {
    const x = Number(n);
    return Number.isFinite(x) ? x : 0;
}

function SimpleTable({ columns = [], rows = [], rowKeyPrefix = 'r' }) {
    if (!rows || rows.length === 0) return null;

    return (
        <div className="overflow-x-auto border border-[var(--border)] rounded-xl bg-white">
            <table className="min-w-full text-sm">
                <thead className="bg-gray-50">
                    <tr>
                        {columns.map((c) => (
                            <th key={c} className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                                {c}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r, idx) => (
                        <tr key={`${rowKeyPrefix}-${idx}`} className="border-t border-[var(--border)]">
                            {columns.map((c) => (
                                <td key={c} className="px-3 py-2 whitespace-nowrap">
                                    {r?.[c] ?? ''}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function MaterialsTable({ materials }) {
    if (!materials?.rows?.length) return null;

    const rows = materials.rows.map((r) => ({
        code: r.code ?? '',
        descr: r.descr ?? '',
        um: r.um ?? '',
        qta: safeNum(r.qta).toFixed(2),
        prezzo: formatEuro(r.prezzo),
        totale: formatEuro(r.totale),
    }));

    return (
        <SimpleTable
            columns={['code', 'descr', 'um', 'qta', 'prezzo', 'totale']}
            rows={rows}
            rowKeyPrefix="mat"
        />
    );
}

function LaborTable({ labor }) {
    if (!labor?.rows?.length) return null;

    const rows = labor.rows.map((r) => ({
        ruolo: r.ruolo ?? '',
        ore: safeNum(r.ore).toFixed(2),
        tariffa: formatEuro(r.tariffa),
        totale: formatEuro(r.totale),
    }));

    return (
        <SimpleTable
            columns={['ruolo', 'ore', 'tariffa', 'totale']}
            rows={rows}
            rowKeyPrefix="lab"
        />
    );
}

function EstimateBlock({ uiTables }) {
    if (!uiTables?.items?.length) return null;

    const items = uiTables.items || [];
    const grandTotal = safeNum(uiTables.grand_total);
    const subtotal = safeNum(uiTables.subtotal);
    const marginPct = uiTables.margin_pct;
    const marginAmount = safeNum(uiTables.margin_amount);

    return (
        <div className="mt-3 space-y-3">
            <div className="p-3 rounded-xl border border-[var(--border)] bg-white">
                <div className="flex flex-wrap items-center gap-3">
                    <div className="font-bold">Preventivo</div>
                    {Number.isFinite(subtotal) && (
                        <div className="text-sm text-[var(--muted)]">
                            Subtotale: <span className="font-semibold text-gray-900">{formatEuro(subtotal)}</span>
                        </div>
                    )}
                    {marginPct != null && (
                        <div className="text-sm text-[var(--muted)]">
                            Margine: <span className="font-semibold text-gray-900">{marginPct}%</span>
                            {Number.isFinite(marginAmount) ? (
                                <span className="ml-1">({formatEuro(marginAmount)})</span>
                            ) : null}
                        </div>
                    )}
                    <div className="text-sm text-[var(--muted)]">
                        Totale: <span className="font-semibold text-gray-900">{formatEuro(grandTotal)}</span>
                    </div>
                </div>
            </div>

            <div className="p-3 rounded-xl border border-[var(--border)] bg-white">
                <div className="font-semibold mb-2">Lavorazioni</div>
                <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                        <thead className="bg-gray-50">
                            <tr>
                                <th className="text-left px-3 py-2">Voce</th>
                                <th className="text-left px-3 py-2">Q.tà</th>
                                <th className="text-left px-3 py-2">UM</th>
                                <th className="text-left px-3 py-2">Subtotale</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map((it, idx) => (
                                <tr key={`sum-${idx}`} className="border-t border-[var(--border)]">
                                    <td className="px-3 py-2">{it.label || it.work_name || it.work_code || `Voce ${idx + 1}`}</td>
                                    <td className="px-3 py-2">{safeNum(it.qty).toFixed(2)}</td>
                                    <td className="px-3 py-2">{it.unit || ''}</td>
                                    <td className="px-3 py-2 font-semibold">{formatEuro(it.subtotal)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {items.map((it, idx) => (
                <div key={`it-${idx}`} className="p-3 rounded-xl border border-[var(--border)] bg-white space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                            <div className="font-semibold">
                                {it.label || it.work_name || it.work_code || `Voce ${idx + 1}`}
                            </div>
                            {it.work_code ? (
                                <div className="text-xs text-[var(--muted)]">Codice: {it.work_code}</div>
                            ) : null}
                            {Array.isArray(it.applied_factors) && it.applied_factors.length > 0 ? (
                                <div className="text-xs text-[var(--muted)]">
                                    Fattori: {it.applied_factors.join(', ')}
                                </div>
                            ) : null}
                        </div>
                        <div className="text-sm text-[var(--muted)]">
                            Subtotale: <span className="font-semibold text-gray-900">{formatEuro(it.subtotal)}</span>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                        <div>
                            <div className="text-sm font-semibold mb-2">Materiali</div>
                            {it.materials?.rows?.length ? (
                                <MaterialsTable materials={it.materials} />
                            ) : (
                                <div className="text-sm text-[var(--muted)]">Nessun materiale.</div>
                            )}
                        </div>
                        <div>
                            <div className="text-sm font-semibold mb-2">Manodopera</div>
                            {it.labor?.rows?.length ? (
                                <LaborTable labor={it.labor} />
                            ) : (
                                <div className="text-sm text-[var(--muted)]">Nessuna manodopera.</div>
                            )}
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}

export default function CompanyChat() {
    const [messages, setMessages] = useState([
        { role: 'assistant', text: "Benvenuto! Chat generale dell'azienda." }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    const scrollRef = useRef(null);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        el.scrollTop = el.scrollHeight;
    }, [messages, loading]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages((prev) => [...prev, { role: 'user', text: userMessage }]);
        setLoading(true);

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMessage }),
            });

            const data = await response.json();
            const reply = data.reply || data.answer || data.text || 'OK';

            setMessages((prev) => [
                ...prev,
                {
                    role: 'assistant',
                    text: reply,
                    sources: data.sources || [],
                    ui_tables: data.ui_tables || null,
                    intent: data.intent || null,
                    parsed_items: data.parsed_items || null,
                },
            ]);
        } catch (error) {
            setMessages((prev) => [
                ...prev,
                { role: 'assistant', text: `Errore: ${error.message}` },
            ]);
        } finally {
            setLoading(false);
        }
    };

    const handleReset = () => {
        setMessages([{ role: 'assistant', text: 'Chat resettata. Come posso aiutarti?' }]);
    };

    return (
        <Card className="flex flex-col h-full min-h-0">
            <div>
                <h3 className="text-lg font-bold mb-1">Chat (Azienda)</h3>
                <p className="text-xs text-[var(--muted)] mb-3">Contesto: azienda</p>
            </div>

            {/* ✅ area messaggi: cresce e scrolla (min-h-0 è LA chiave) */}
            <div
                ref={scrollRef}
                className="flex-1 min-h-0 border border-[var(--border)] rounded-xl p-3 overflow-y-auto bg-[#fafafa]"
            >
                {messages.map((msg, idx) => (
                    <div key={idx} className="mb-4 flex gap-2">
                        <div className="font-semibold text-xs text-[var(--muted)] min-w-[60px]">
                            {msg.role === 'user' ? 'Tu' : 'Assistant'}
                        </div>

                        <div className="flex-1">
                            <div
                                className={`inline-block px-3 py-2 rounded-2xl text-sm max-w-full break-words whitespace-pre-wrap ${msg.role === 'user'
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-gray-200 text-gray-900'
                                    }`}
                            >
                                {msg.text}
                            </div>

                            {msg.role === 'assistant' && msg.ui_tables?.items?.length ? (
                                <EstimateBlock uiTables={msg.ui_tables} />
                            ) : null}

                            {msg.sources && msg.sources.length > 0 && (
                                <div className="mt-3 text-xs text-[var(--muted)] p-3 rounded-xl border border-[var(--border)] bg-white">
                                    <div className="font-semibold mb-1">Fonti</div>
                                    {msg.sources.map((s, i) => (
                                        <div key={i} className="truncate">
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

            {/* ✅ form sempre visibile in basso */}
            <form onSubmit={handleSubmit} className="flex gap-2 mt-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Scrivi un messaggio... (es: 'Posa pavimento 50 mq in Lazio')"
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