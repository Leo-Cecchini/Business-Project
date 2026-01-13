import { useState } from 'react';
import { useCompanyOverview, useDashboardSummary } from '../api/queries';
import Card from '../components/ui/Card';
import KPICard from '../components/ui/KPICard';
import Button from '../components/ui/Button';
import CompanyChat from '../components/azienda/CompanyChat';
import CreateProjectModal from '../components/modals/CreateProjectModal';
import CreateWorkerModal from '../components/modals/CreateWorkerModal';
import DeleteWorkerModal from '../components/modals/DeleteWorkerModal';

export default function Azienda() {
    const { data: overview, isLoading: overviewLoading } = useCompanyOverview();
    const { data: dashboard, isLoading: dashboardLoading } = useDashboardSummary();

    const [showCreateProject, setShowCreateProject] = useState(false);
    const [showCreateWorker, setShowCreateWorker] = useState(false);
    const [showDeleteWorker, setShowDeleteWorker] = useState(false);

    const isLoading = overviewLoading || dashboardLoading;

    return (
        <div className="h-full min-h-0 flex flex-col gap-4">
            {/* KPI Section (non deve crescere) */}
            <div className="shrink-0">
                <Card>
                    <h2 className="text-xl font-bold mb-3">Panoramica azienda</h2>
                    <p className="text-sm text-[var(--muted)] mb-4">Numeri aggiornati dal DB.</p>

                    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
                        <KPICard title="Operai" value={overview?.stats?.workers_total ?? dashboard?.stats?.workers_total} loading={isLoading} />
                        <KPICard title="Cantieri" value={overview?.stats?.projects_total ?? dashboard?.stats?.projects_total} loading={isLoading} />
                        <KPICard title="Cantieri attivi" value={overview?.stats?.active_projects ?? dashboard?.stats?.active_projects} loading={isLoading} />
                        <KPICard title="Operai attivi" value={overview?.stats?.active_workers ?? dashboard?.stats?.active_workers} loading={isLoading} />
                        <KPICard title="Documenti" value={overview?.stats?.documents_total ?? dashboard?.stats?.documents_total} loading={isLoading} />
                    </div>

                    <div className="flex flex-wrap gap-2">
                        <Button onClick={() => setShowCreateWorker(true)}>+ Aggiungi operaio</Button>
                        <Button variant="danger" onClick={() => setShowDeleteWorker(true)}>− Rimuovi operaio</Button>
                        <Button variant="primary" onClick={() => setShowCreateProject(true)}>+ Crea cantiere</Button>
                    </div>
                </Card>
            </div>

            {/* Chat prende tutto lo spazio rimanente */}
            <div className="flex-1 min-h-0">
                <CompanyChat />
            </div>

            {/* Modals */}
            <CreateProjectModal isOpen={showCreateProject} onClose={() => setShowCreateProject(false)} />
            <CreateWorkerModal isOpen={showCreateWorker} onClose={() => setShowCreateWorker(false)} />
            <DeleteWorkerModal isOpen={showDeleteWorker} onClose={() => setShowDeleteWorker(false)} />
        </div>
    );
}