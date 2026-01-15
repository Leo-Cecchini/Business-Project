import { useApp } from '../../context/AppContext';
import { useProjects } from '../../api/queries';

export default function ProjectSelector() {
    const { selectedProjectId, selectProject, clearProject } = useApp();
    const { data: projects = [], isLoading } = useProjects();

    const handleChange = (e) => {
        const projectId = e.target.value;
        if (!projectId) {
            clearProject();
        } else {
            const project = projects.find(p => String(p.id) === projectId);
            selectProject(projectId, project?.name || project?.nome || '');
        }
    };

    return (
        <select
            value={selectedProjectId}
            onChange={handleChange}
            disabled={isLoading}
            className="px-3 py-1.5 border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)] bg-white"
        >
            <option value="">— Nessuno —</option>
            {projects.map((project) => (
                <option key={project.id} value={project.id}>
                    {project.name || project.nome || `Progetto ${project.id}`}
                </option>
            ))}
        </select>
    );
}