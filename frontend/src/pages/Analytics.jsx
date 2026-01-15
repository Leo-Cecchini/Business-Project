import { useState } from 'react';
import {
    useAnalyticsSummary,
    useAnalyticsReports,
    useGenerateAnalyticsReport
} from '../api/queries';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { toast } from '../components/ui/Toast';

export default function Analytics() {
    const { data: summary } = useAnalyticsSummary();
    const { data: reports = [] } = useAnalyticsReports();
    const generateMutation = useGenerateAnalyticsReport();

    const [periodDays, setPeriodDays] = useState(7);

    const handleGenerateReport = async () => {
        try {
            await generateMutation.mutateAsync(periodDays);
            toast('Report generato con successo', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    return (
        <div className="space-y-4">
            {/* KPI Summary */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                    <div>
                        <p className="text-sm text-[var(--muted)]">Conversazioni Totali</p>
                        <p className="text-3xl font-bold">{summary?.total_chats || 0}</p>
                    </div>
                </Card>
                <Card>
                    <div>
                        <p className="text-sm text-[var(--muted)]">Ultimi 7 giorni</p>
                        <p className="text-3xl font-bold">{summary?.last_days_chats || 0}</p>
                    </div>
                </Card>
                <Card>
                    <div>
                        <p className="text-sm text-[var(--muted)]">Tasso di Errore</p>
                        <p className="text-3xl font-bold">
                            {((summary?.error_rate || 0) * 100).toFixed(1)}%
                        </p>
                    </div>
                </Card>
            </div>

            {/* Generate Report */}
            <Card>
                <h3 className="text-lg font-bold mb-4">Genera Nuovo Report</h3>
                <div className="flex gap-3">
                    <Input
                        type="number"
                        value={periodDays}
                        onChange={(e) => setPeriodDays(parseInt(e.target.value) || 7)}
                        label="Periodo (giorni)"
                        min="1"
                        max="90"
                    />
                    <div className="flex items-end">
                        <Button
                            variant="primary"
                            onClick={handleGenerateReport}
                            disabled={generateMutation.isPending}
                        >
                            {generateMutation.isPending ? 'Generazione...' : 'Genera Report'}
                        </Button>
                    </div>
                </div>
            </Card>

            {/* Reports List */}
            <Card>
                <h3 className="text-lg font-bold mb-4">Report Recenti</h3>
                {reports.length === 0 ? (
                    <p className="text-[var(--muted)] text-center py-8">
                        Nessun report disponibile
                    </p>
                ) : (
                    <div className="space-y-3">
                        {reports.map((report, idx) => (
                            <div
                                key={idx}
                                className="border border-[var(--border)] rounded-xl p-4 hover:shadow-md transition-shadow"
                            >
                                <div className="flex justify-between items-start mb-2">
                                    <div>
                                        <p className="font-semibold">Report {report.period_days} giorni</p>
                                        <p className="text-xs text-[var(--muted)]">
                                            {new Date(report.created_at).toLocaleDateString('it-IT')}
                                        </p>
                                    </div>
                                    {report.metrics && (
                                        <div className="text-right">
                                            <p className="text-sm">
                                                <span className="text-[var(--muted)]">Accuratezza:</span>{' '}
                                                <span className="font-semibold">
                                                    {(report.metrics.accuracy * 100).toFixed(0)}%
                                                </span>
                                            </p>
                                        </div>
                                    )}
                                </div>
                                {report.report && (
                                    <div className="mt-3 p-3 bg-gray-50 rounded-lg">
                                        <pre className="text-xs whitespace-pre-wrap">{report.report}</pre>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </Card>
        </div>
    );
}