import { useState } from 'react';
import { useWorkers } from '../../api/queries';  // ✅ Add import
import Button from '../ui/Button';
import { format } from 'date-fns';
import { it } from 'date-fns/locale';

export default function WorkCard({ work, projectId, onAssignWorker, onRemoveWorker, onUpdateStatus }) {
    const [expanded, setExpanded] = useState(false);
    
    // ✅ Fetch all workers for name lookup
    const { data: workersData } = useWorkers();
    const allWorkers = Array.isArray(workersData) ? workersData : (workersData?.items || []);
    
    // ✅ Create lookup map: ID -> worker object
    const workersMap = allWorkers.reduce((acc, w) => {
        acc[w.id] = w;
        return acc;
    }, {});

    const getStatusColor = (status) => {
        const colors = {
            planned: 'bg-blue-50 text-blue-800 border-blue-200',
            in_progress: 'bg-yellow-50 text-yellow-800 border-yellow-200',
            completed: 'bg-green-50 text-green-800 border-green-200',
            on_hold: 'bg-gray-50 text-gray-800 border-gray-200',
        };
        return colors[status] || colors.planned;
    };

    const getStatusLabel = (status) => {
        const labels = {
            planned: 'Pianificato',
            in_progress: 'In corso',
            completed: 'Completato',
            on_hold: 'In pausa',
        };
        return labels[status] || status;
    };

    const formatDate = (dateStr) => {
        if (!dateStr) return '—';
        try {
            return format(new Date(dateStr), 'dd MMM yyyy', { locale: it });
        } catch {
            return dateStr;
        }
    };

    const hasWorkers = work.workers && work.workers.length > 0;
    const isCompleted = work.status === 'completed';

    return (
        <div className="border border-[var(--border)] rounded-xl overflow-hidden hover:shadow-md transition-shadow">
            {/* Header */}
            <div className="bg-gray-50 p-4">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                            <h3 className="font-bold text-base">{work.work_name}</h3>
                            <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium border ${getStatusColor(work.status)}`}>
                                {getStatusLabel(work.status)}
                            </span>
                        </div>

                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                            <div>
                                <span className="text-xs text-[var(--muted)]">Inizio pianificato</span>
                                <p className="font-medium">{formatDate(work.start_date_planned)}</p>
                            </div>
                            <div>
                                <span className="text-xs text-[var(--muted)]">Fine pianificata</span>
                                <p className="font-medium">{formatDate(work.end_date_planned)}</p>
                            </div>
                            <div>
                                <span className="text-xs text-[var(--muted)]">Ore stimate</span>
                                <p className="font-medium">{work.duration_estimated_hours || '—'} h</p>
                            </div>
                            <div>
                                <span className="text-xs text-[var(--muted)]">Operai richiesti</span>
                                <p className="font-medium">{work.number_of_workers || 1}</p>
                            </div>
                        </div>
                    </div>

                    <button
                        onClick={() => setExpanded(!expanded)}
                        className="text-xl text-gray-600 hover:text-gray-900 transition-colors"
                    >
                        {expanded ? '▼' : '▶'}
                    </button>
                </div>
            </div>

            {/* Expanded Content */}
            {expanded && (
                <div className="p-4 space-y-4">
                    {/* Workers Assigned */}
                    <div>
                        <div className="flex items-center justify-between mb-3">
                            <h4 className="font-semibold text-sm">Operai Assegnati ({hasWorkers ? work.workers.length : 0}/{work.number_of_workers || 1})</h4>
                            {!isCompleted && (
                                <Button
                                    onClick={() => onAssignWorker(work)}
                                    className="!py-1 !px-3 text-xs"
                                >
                                    + Assegna Operaio
                                </Button>
                            )}
                        </div>

                        {hasWorkers ? (
                            <div className="space-y-2">
                                {work.workers.map((workerId, idx) => {
                                    // ✅ workerId is a string (ObjectId), lookup full worker data
                                    const workerData = workersMap[workerId];
                                    const workerName = workerData?.name || `Worker ${workerId.slice(-4)}`;
                                    const workerRole = workerData?.role;
                                    
                                    return (
                                        <div
                                            key={workerId || idx}
                                            className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-[var(--border)]"
                                        >
                                            <div className="flex-1">
                                                <p className="font-medium text-sm">{workerName}</p>
                                                {workerRole && (
                                                    <p className="text-xs text-[var(--muted)]">{workerRole}</p>
                                                )}
                                            </div>
                                            {!isCompleted && (
                                                <Button
                                                    variant="danger"
                                                    onClick={() => onRemoveWorker(work, { worker_id: workerId, id: workerId })}
                                                    className="!py-1 !px-2 text-xs"
                                                >
                                                    Rimuovi
                                                </Button>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        ) : (
                            <p className="text-sm text-[var(--muted)] italic">Nessun operaio assegnato</p>
                        )}
                    </div>

                    {/* Status Actions */}
                    {!isCompleted && (
                        <div>
                            <h4 className="font-semibold text-sm mb-2">Aggiorna Stato</h4>
                            <div className="flex gap-2 flex-wrap">
                                {work.status !== 'in_progress' && (
                                    <Button
                                        onClick={() => onUpdateStatus(work, 'in_progress')}
                                        className="text-xs"
                                    >
                                        ▶️ Inizia Lavoro
                                    </Button>
                                )}
                                {work.status === 'in_progress' && (
                                    <Button
                                        onClick={() => onUpdateStatus(work, 'on_hold')}
                                        className="text-xs"
                                    >
                                        ⏸️ Metti in Pausa
                                    </Button>
                                )}
                                {work.status !== 'completed' && (
                                    <Button
                                        variant="primary"
                                        onClick={() => onUpdateStatus(work, 'completed')}
                                        className="text-xs"
                                    >
                                        ✅ Segna Completato
                                    </Button>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Actual Dates (if started) */}
                    {(work.start_date_actual || work.end_date_actual) && (
                        <div>
                            <h4 className="font-semibold text-sm mb-2">Date Effettive</h4>
                            <div className="grid grid-cols-2 gap-3 text-sm">
                                <div>
                                    <span className="text-xs text-[var(--muted)]">Inizio effettivo</span>
                                    <p className="font-medium">{formatDate(work.start_date_actual)}</p>
                                </div>
                                <div>
                                    <span className="text-xs text-[var(--muted)]">Fine effettiva</span>
                                    <p className="font-medium">{formatDate(work.end_date_actual)}</p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}