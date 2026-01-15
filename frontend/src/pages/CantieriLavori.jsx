import { useState } from 'react';
import { useApp } from '../context/AppContext';
import {
    useProject,
    useGenerateLavori,
    useAssignWorkerToWork,
    useRemoveWorkerFromWork,
    useUpdateWorkStatus,
} from '../api/queries';
import { useNavigate } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import WorkCard from '../components/cantieri/WorkCard';
import AssignWorkerModal from '../components/cantieri/AssignWorkerModal';
import { toast } from '../components/ui/Toast';

export default function CantieriLavori() {
    const { selectedProjectId } = useApp();
    const { data: project } = useProject(selectedProjectId);
    const navigate = useNavigate();

    const [selectedWork, setSelectedWork] = useState(null);
    const [showAssignModal, setShowAssignModal] = useState(false);
    const [startDate, setStartDate] = useState('');

    const lavoriMutation = useGenerateLavori();
    const assignMutation = useAssignWorkerToWork();
    const removeMutation = useRemoveWorkerFromWork();
    const updateStatusMutation = useUpdateWorkStatus();

    const works = project?.works || [];
    const hasComputo = project?.meta_extra?.computo_metrico?.bill_of_quantities ||
        project?.meta_extra?.computo?.bill_of_quantities ||
        project?.computo?.bill_of_quantities;

    const handleGenerateLavori = async () => {
        if (!startDate) {
            toast('Seleziona una data di inizio lavori', 'error');
            return;
        }

        try {
            const result = await lavoriMutation.mutateAsync({
                projectId: selectedProjectId,
                startDate
            });

            const workCount = result?.works?.length || 0;
            toast(`Sequenza lavori generata! ${workCount} voci create.`, 'success');

            setStartDate('');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleAssignWorker = (work) => {
        setSelectedWork(work);
        setShowAssignModal(true);
    };

    const handleConfirmAssign = async (data) => {
        if (!selectedWork) return;

        try {
            await assignMutation.mutateAsync({
                projectId: selectedProjectId,
                workName: selectedWork.work_name,
                workerId: data.workerId,
                startDate: data.startDate,
                endDate: data.endDate,
            });

            toast('Operaio assegnato con successo', 'success');
            setShowAssignModal(false);
            setSelectedWork(null);
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleRemoveWorker = async (work, worker) => {
        // WorkCard passa spesso una stringa (workerId). Manteniamo compatibilità
        // anche se in futuro passasse un oggetto worker.
        console.log('handleRemoveWorker called:', { work: work.work_name, worker });

        const workerId =
            typeof worker === 'string'
                ? worker
                : (worker?.worker_id || worker?.id || worker?._id);

        // Recupera il nome se possibile
        const workerObj =
            typeof worker === 'object' && worker
                ? worker
                : (workersData || []).find(w => (w.id || w._id) === workerId);

        const workerName = workerObj?.name || workerObj?.worker_name || (workerId ? `Worker ${String(workerId).slice(-4)}` : 'operaio');

        if (!workerId) {
            toast('ID operaio non valido', 'error');
            return;
        }

        if (!window.confirm(`Rimuovere ${workerName} da questo lavoro?`)) return;

        console.log('Sending unassign request:', {
            projectId: selectedProjectId,
            workName: work.work_name,
            workerId,
        });

        try {
            await removeMutation.mutateAsync({
                projectId: selectedProjectId,
                workName: work.work_name,
                workerId,
            });

            toast('Operaio rimosso', 'success');
        } catch (error) {
            console.error('Remove worker error:', error);
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleUpdateStatus = async (work, newStatus) => {
        try {
            await updateStatusMutation.mutateAsync({
                projectId: selectedProjectId,
                workName: work.work_name,
                status: newStatus,
            });

            toast('Stato aggiornato', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    if (!selectedProjectId) {
        return (
            <Card>
                <div className="text-center py-12">
                    <p className="text-lg text-[var(--muted)] mb-4">
                        Nessun cantiere selezionato
                    </p>
                    <p className="text-sm text-[var(--muted)]">
                        Seleziona un cantiere dalla lista a destra
                    </p>
                </div>
            </Card>
        );
    }

    // Se non ci sono lavori, mostra la sezione di generazione
    if (!works.length) {
        return (
            <div className="space-y-4">
                <Card>
                    <h2 className="text-xl font-bold mb-2">Genera Sequenza Lavori</h2>
                    <p className="text-sm text-[var(--muted)] mb-4">
                        {project?.name || project?.nome}
                    </p>

                    {!hasComputo ? (
                        <div className="bg-orange-50 border border-orange-200 rounded-xl p-4">
                            <p className="text-sm text-orange-800 font-semibold mb-2">
                                ⚠️ Computo metrico non disponibile
                            </p>
                            <p className="text-sm text-orange-700 mb-4">
                                Per generare la sequenza lavori è necessario prima creare un computo metrico.
                            </p>
                            <Button onClick={() => navigate('/cantieri/computo')}>
                                Vai al Computo Metrico →
                            </Button>
                        </div>
                    ) : (
                        <>
                            <p className="text-sm text-green-600 mb-4">
                                ✅ Computo metrico disponibile, puoi generare la sequenza lavori
                            </p>

                            <div className="flex gap-3">
                                <Input
                                    type="date"
                                    value={startDate}
                                    onChange={(e) => setStartDate(e.target.value)}
                                    label="Data inizio lavori"
                                    className="flex-1"
                                />
                                <div className="flex items-end">
                                    <Button
                                        variant="primary"
                                        onClick={handleGenerateLavori}
                                        disabled={lavoriMutation.isPending}
                                    >
                                        {lavoriMutation.isPending ? 'Generazione...' : 'Genera Sequenza Lavori'}
                                    </Button>
                                </div>
                            </div>
                        </>
                    )}
                </Card>
            </div>
        );
    }

    // Se ci sono lavori, mostra la visualizzazione normale
    const worksByStatus = {
        planned: works.filter(w => w.status === 'planned'),
        in_progress: works.filter(w => w.status === 'in_progress'),
        completed: works.filter(w => w.status === 'completed'),
        on_hold: works.filter(w => w.status === 'on_hold'),
    };

    const totalWorks = works.length;
    const completedCount = worksByStatus.completed.length;
    const progressPercent = totalWorks > 0 ? Math.round((completedCount / totalWorks) * 100) : 0;

    return (
        <div className="space-y-4">
            {/* Header with stats */}
            <Card>
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h2 className="text-xl font-bold">Sequenza Lavori</h2>
                        <p className="text-sm text-[var(--muted)]">
                            {project?.name || project?.nome}
                        </p>
                    </div>
                    <div className="text-right">
                        <p className="text-sm text-[var(--muted)]">Avanzamento</p>
                        <p className="text-2xl font-bold text-[var(--brand)]">
                            {progressPercent}%
                        </p>
                        <p className="text-xs text-[var(--muted)]">
                            {completedCount} di {totalWorks} completati
                        </p>
                    </div>
                </div>

                {/* Progress bar */}
                <div className="w-full bg-gray-200 rounded-full h-3">
                    <div
                        className="bg-[var(--brand)] h-3 rounded-full transition-all duration-300"
                        style={{ width: `${progressPercent}%` }}
                    />
                </div>

                {/* Quick stats */}
                <div className="grid grid-cols-4 gap-3 mt-4">
                    <div className="text-center p-3 bg-blue-50 rounded-lg border border-blue-200">
                        <p className="text-2xl font-bold text-blue-800">{worksByStatus.planned.length}</p>
                        <p className="text-xs text-blue-600">Pianificati</p>
                    </div>
                    <div className="text-center p-3 bg-yellow-50 rounded-lg border border-yellow-200">
                        <p className="text-2xl font-bold text-yellow-800">{worksByStatus.in_progress.length}</p>
                        <p className="text-xs text-yellow-600">In Corso</p>
                    </div>
                    <div className="text-center p-3 bg-green-50 rounded-lg border border-green-200">
                        <p className="text-2xl font-bold text-green-800">{worksByStatus.completed.length}</p>
                        <p className="text-xs text-green-600">Completati</p>
                    </div>
                    <div className="text-center p-3 bg-gray-50 rounded-lg border border-gray-200">
                        <p className="text-2xl font-bold text-gray-800">{worksByStatus.on_hold.length}</p>
                        <p className="text-xs text-gray-600">In Pausa</p>
                    </div>
                </div>
            </Card>

            {/* Works List */}
            <div className="space-y-3">
                {works.map((work, idx) => (
                    <WorkCard
                        key={idx}
                        work={work}
                        projectId={selectedProjectId}
                        onAssignWorker={handleAssignWorker}
                        onRemoveWorker={handleRemoveWorker}
                        onUpdateStatus={handleUpdateStatus}
                    />
                ))}
            </div>

            {/* Assign Worker Modal */}
            <AssignWorkerModal
                isOpen={showAssignModal}
                onClose={() => {
                    setShowAssignModal(false);
                    setSelectedWork(null);
                }}
                work={selectedWork}
                onAssign={handleConfirmAssign}
            />
        </div>
    );
}