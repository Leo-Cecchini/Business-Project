import Card from '../ui/Card';

export default function ReportsList({ reports = [], isLoading }) {
    if (isLoading) {
        return (
            <Card>
                <p className="text-sm text-[var(--muted)]">Caricamento report...</p>
            </Card>
        );
    }

    if (!reports || reports.length === 0) {
        return (
            <Card>
                <p className="text-sm text-[var(--muted)]">
                    Nessun report presente. Genera uno con il pulsante "Genera report".
                </p>
            </Card>
        );
    }

    return (
        <div className="space-y-3">
            {reports.map((report, idx) => (
                <Card key={idx}>
                    <div className="flex justify-between items-start mb-3">
                        <div>
                            <p className="text-xs text-[var(--muted)]">
                                Creato: {report.created_at || '—'}
                            </p>
                            <p className="text-xs text-[var(--muted)]">
                                Periodo: {report.period_days || 0} giorni
                            </p>
                        </div>
                    </div>

                    <div className="whitespace-pre-wrap text-sm mb-3">
                        {report.report || 'Nessun contenuto disponibile'}
                    </div>

                    {/* Metrics */}
                    {report.metrics && (
                        <details className="mt-3">
                            <summary className="cursor-pointer text-sm font-semibold text-[var(--brand)] hover:underline">
                                Mostra metriche
                            </summary>
                            <pre className="mt-2 p-3 bg-gray-50 rounded-lg overflow-x-auto text-xs">
                                {JSON.stringify(report.metrics, null, 2)}
                            </pre>
                        </details>
                    )}

                    {/* Bad examples */}
                    {report.bad_examples && report.bad_examples.length > 0 && (
                        <details className="mt-3">
                            <summary className="cursor-pointer text-sm font-semibold text-[var(--brand)] hover:underline">
                                Esempi problematici ({report.bad_examples.length})
                            </summary>
                            <ul className="mt-2 space-y-2">
                                {report.bad_examples.map((example, i) => (
                                    <li key={i} className="p-2 border border-[var(--border)] rounded-lg">
                                        <div className="text-sm">
                                            <strong>Q:</strong> {example.q || '—'}
                                        </div>
                                        <div className="text-sm">
                                            <strong>A:</strong> {example.a || '—'}
                                        </div>
                                        <div className="text-xs text-[var(--muted)] mt-1">
                                            {example.ts || ''}
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </details>
                    )}
                </Card>
            ))}
        </div>
    );
}