import { useState } from 'react';
import { useApp } from '../context/AppContext';
import { useProject } from '../api/queries';
import Card from '../components/ui/Card';
import SiteHeader from '../components/cantieri/SiteHeader';
import SiteDocuments from '../components/cantieri/SiteDocuments';
import SiteChat from '../components/cantieri/SiteChat';

export default function CantieriOverview() {
    const { selectedProjectId, clearProject } = useApp();
    const { data: currentProject } = useProject(selectedProjectId);

    const [showDocuments, setShowDocuments] = useState(false);

    if (!selectedProjectId) {
        return (
            <Card>
                <div className="text-center py-12">
                    <p className="text-lg text-[var(--muted)] mb-4">
                        Nessun cantiere selezionato
                    </p>
                    <p className="text-sm text-[var(--muted)] mb-6">
                        Seleziona un cantiere dalla lista a destra
                    </p>
                </div>
            </Card>
        );
    }

    return (
        <div className="space-y-4">
            {/* Header cantiere */}
            <SiteHeader project={currentProject} onClear={clearProject} />

            {/* Toggle Documenti */}
            <Card>
                <button
                    onClick={() => setShowDocuments(!showDocuments)}
                    className="w-full flex items-center justify-between p-1 hover:bg-gray-50 rounded-lg transition-colors"
                >
                    <div className="flex items-center gap-3">
                        <span className="text-xl">{showDocuments ? '▼' : '▶'}</span>
                        <div className="text-left">
                            <h3 className="font-bold">Documenti Cantiere</h3>
                            <p className="text-sm text-[var(--muted)]">
                                Carica e gestisci documenti specifici del cantiere
                            </p>
                        </div>
                    </div>
                </button>

                {showDocuments && (
                    <div className="mt-4 pt-4 border-t border-[var(--border)]">
                        <SiteDocuments projectId={selectedProjectId} />
                    </div>
                )}
            </Card>

            {/* Chat cantiere */}
            <SiteChat projectId={selectedProjectId} />
        </div>
    );
}