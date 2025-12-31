import { useState } from 'react';
import { useApp } from '../../context/AppContext';
import {
    useToggleProjectStatus,
    useDeleteProject,
    usePlanProject,
    useAssignWorkers,
} from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';
import CreateProjectModal from '../modals/CreateProjectModal';

export default function SiteHeader({ project, onClear }) {
    const { selectedProjectId } = useApp();
    const toggleStatusMutation = useToggleProjectStatus();
    const deleteProjectMutation = useDeleteProject();
    const planMutation = usePlanProject();
    const assignMutation = useAssignWorkers();
    const [showCreateProject, setShowCreateProject] = useState(false);

    const status = project?.status || project?.stato || 'Preventivo';
    const isConfirmed = status === 'Confermato';

    // Check if project has planned works
    const hasPlannedWorks = project?.works?.some(w =>
        w.start_date_planned || w.start_planned || w.start_date
    );

    const handleToggleStatus = async () => {
        if (!selectedProjectId) return;

        try {
            await toggleStatusMutation.mutateAsync(selectedProjectId);
            toast('Stato cantiere aggiornato', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleDelete = async () => {
        if (!selectedProjectId || !project) return;

        const confirmed = window.confirm(
            `Eliminare DEFINITIVAMENTE il cantiere "${project.name || project.nome}"?`
        );

        if (!confirmed) return;

        try {
            await deleteProjectMutation.mutateAsync(selectedProjectId);
            onClear();
            toast('Cantiere eliminato', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handlePlanOrAssign = async () => {
        if (!selectedProjectId) return;

        // If not planned yet, do planning
        if (!hasPlannedWorks) {
            try {
                await planMutation.mutateAsync({
                    projectId: selectedProjectId,
                    startFrom: 'auto',
                    replace: true
                });
                toast('Pianificazione completata', 'success');
            } catch (error) {
                toast(`Errore pianificazione: ${error.message}`, 'error');
            }
            return;
        }

        // If planned but not confirmed, warn user
        if (!isConfirmed) {
            toast('Per assegnare operai, porta lo stato a "Confermato"', 'warning');
            return;
        }

        // Do assignment
        try {
            const result = await assignMutation.mutateAsync(selectedProjectId);

            const assigned = result?.assigned || 0;
            const deficits = result?.deficits || [];

            if (deficits.length > 0) {
                const byRole = {};
                deficits.forEach(d => {
                    const key = (d.role || d.work_code || 'ruolo').toString();
                    const miss = Math.max(0, (d.needed || 1) - (d.found || 0)) || 1;
                    byRole[key] = (byRole[key] || 0) + miss;
                });

                const parts = Object.entries(byRole).map(([k, v]) => `${k}: ${v}`);
                toast(`Assegnati ${assigned}. Mancano → ${parts.join(' | ')}`, 'warning');
            } else {
                toast(`Assegnati ${assigned} slot.`, 'success');
            }
        } catch (error) {
            toast(`Errore assegnazione: ${error.message}`, 'error');
        }
    };

    if (!project) {
        return (
            <>
                <Card>
                    <div className="flex items-center justify-between">
                        <h2 className="text-2xl font-bold">Nessun cantiere selezionato</h2>
                        <Button variant="primary" onClick={() => setShowCreateProject(true)}>
                            + Crea cantiere
                        </Button>
                    </div>
                </Card>
                <CreateProjectModal
                    isOpen={showCreateProject}
                    onClose={() => setShowCreateProject(false)}
                />
            </>
        );
    }

    const buttonLabel = !hasPlannedWorks
        ? 'Pianifica'
        : isConfirmed
            ? 'Assegna operai'
            : 'Pianifica';

    const buttonTooltip = !hasPlannedWorks
        ? 'Calcola le date dei lavori dal catalogo'
        : !isConfirmed
            ? 'Per assegnare porta lo stato a "Confermato"'
            : 'Assegna la squadra sui lavori pianificati';

    return (
        <Card>
            <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                    <h2 className="text-2xl font-bold">
                        {project.name || project.nome || 'Cantiere'}
                    </h2>
                    <span
                        className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium border ${isConfirmed
                                ? 'bg-green-50 text-green-700 border-green-200'
                                : 'bg-orange-50 text-orange-700 border-orange-200'
                            }`}
                    >
                        {isConfirmed ? 'Confermato' : 'Da approvare'}
                    </span>
                </div>

                <div className="flex flex-wrap gap-2">
                    <Button onClick={onClear}>Deseleziona</Button>

                    {!isConfirmed && (
                        <Button
                            variant="primary"
                            onClick={handleToggleStatus}
                            disabled={toggleStatusMutation.isPending}
                        >
                            Segna come Confermato
                        </Button>
                    )}

                    <Button
                        onClick={handlePlanOrAssign}
                        disabled={planMutation.isPending || assignMutation.isPending}
                        title={buttonTooltip}
                    >
                        {planMutation.isPending || assignMutation.isPending
                            ? 'Elaborazione...'
                            : buttonLabel}
                    </Button>

                    <Button
                        variant="danger"
                        onClick={handleDelete}
                        disabled={deleteProjectMutation.isPending}
                    >
                        Elimina cantiere
                    </Button>
                </div>
            </div>

            {/* Info aggiuntive */}
            {(project.location_city || project.city || project.citta) && (
                <div className="mt-3 text-sm text-[var(--muted)]">
                    📍 {project.location_city || project.city || project.citta}
                </div>
            )}

            {project.start_date_estimated && project.end_date_estimated && (
                <div className="mt-2 text-sm text-[var(--muted)]">
                    📅 Date stima: {project.start_date_estimated} → {project.end_date_estimated}
                </div>
            )}

            {/* Works info */}
            {project.works && project.works.length > 0 && (
                <div className="mt-3 flex items-center gap-4 text-sm">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-blue-50 text-blue-700 rounded-lg border border-blue-200">
                        📋 {project.works.length} lavori
                    </span>
                    {hasPlannedWorks && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-green-50 text-green-700 rounded-lg border border-green-200">
                            ✅ Pianificati
                        </span>
                    )}
                </div>
            )}
        </Card>
    );
}