import Card from '../ui/Card';

export default function SitesList({ projects = [], selectedId, onSelect }) {
    if (projects.length === 0) {
        return (
            <Card className="p-4">
                <h3 className="font-bold mb-3">Cantieri</h3>
                <p className="text-sm text-[var(--muted)]">Nessun cantiere disponibile</p>
            </Card>
        );
    }

    return (
        <Card className="p-3">
            <h3 className="font-bold mb-3 px-2">Cantieri</h3>
            <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                {projects.map((project) => {
                    const isActive = String(project.id) === String(selectedId);
                    const status = project.status || project.stato || 'Preventivo';
                    const name = project.name || project.nome || `Progetto ${project.id}`;

                    // ✅ FIX: Priorità addresses.city
                    const city = project.addresses?.city ||
                        project.location_city ||
                        project.city ||
                        project.citta ||
                        '';

                    return (
                        <button
                            key={project.id}
                            onClick={() => onSelect(project.id, name)}
                            className={`w-full text-left p-3 rounded-xl border transition-all ${isActive
                                ? 'bg-[#eef2ff] border-[#c7d2fe]'
                                : 'bg-[#fafafa] border-[var(--border)] hover:bg-gray-50'
                                }`}
                        >
                            <div className="font-semibold text-sm">{name}</div>
                            <div className="text-xs text-[var(--muted)] mt-1">
                                {city && `${city} — `}
                                {status === 'Confermato' ? 'Confermato' : 'Da approvare'}
                            </div>
                        </button>
                    );
                })}
            </div>
        </Card>
    );
}