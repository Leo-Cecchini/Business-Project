import { NavLink } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useProject } from '../../api/queries';
import Card from '../ui/Card';

export default function SiteSidebar() {
    const { selectedProjectId } = useApp();
    const { data: project } = useProject(selectedProjectId);

    if (!selectedProjectId) {
        return null;
    }

    const hasWorks = project?.works && project.works.length > 0;

    const navItems = [
        {
            path: '/cantieri',
            label: 'Panoramica',
            exact: true,
        },
        {
            path: '/cantieri/computo',
            label: 'Computo Metrico',
        },
        {
            path: '/cantieri/lavori',
            label: 'Sequenza Lavori',
            badge: hasWorks ? project.works.length : null,
        },
    ];

    return (
        <Card className="p-3 space-y-2">
            <h3 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wide px-2 mb-2">
                Gestione Cantiere
            </h3>
            {navItems.map((item) => (
                <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.exact}
                >
                    {({ isActive }) => (
                        <div
                            className={`flex items-center justify-between px-3 py-2.5 rounded-xl text-sm transition-colors ${isActive
                                    ? 'bg-[var(--brand)] text-white font-medium'
                                    : 'hover:bg-gray-50'
                                }`}
                        >
                            <span>{item.label}</span>
                            {item.badge && (
                                <span
                                    className={`inline-flex items-center justify-center min-w-[24px] h-6 px-2 text-xs font-bold rounded-full ${isActive
                                            ? 'bg-white text-[var(--brand)]'
                                            : 'bg-blue-100 text-blue-800'
                                        }`}
                                >
                                    {item.badge}
                                </span>
                            )}
                        </div>
                    )}
                </NavLink>
            ))}
        </Card>
    );
}