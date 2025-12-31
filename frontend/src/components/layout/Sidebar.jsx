import { NavLink } from 'react-router-dom';
import Card from '../ui/Card';

export default function Sidebar() {
    const navItems = [
        { path: '/azienda', label: 'Azienda', icon: '🏢' },
        { path: '/cantieri', label: 'Cantieri', icon: '🏗️' },
        { path: '/analytics', label: 'Analytics', icon: '📊' },
    ];

    return (
        <Card className="p-3 space-y-2">
            <h3 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wide px-2 mb-2">
                Menu Principale
            </h3>
            {navItems.map((item) => (
                <NavLink
                    key={item.path}
                    to={item.path}
                >
                    {({ isActive }) => (
                        <div
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors ${isActive
                                    ? 'bg-[var(--brand)] text-white font-medium'
                                    : 'hover:bg-gray-50'
                                }`}
                        >
                            <span className="text-lg">{item.icon}</span>
                            <span>{item.label}</span>
                        </div>
                    )}
                </NavLink>
            ))}
        </Card>
    );
}