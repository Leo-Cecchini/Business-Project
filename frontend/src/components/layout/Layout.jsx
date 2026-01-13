import { Outlet } from 'react-router-dom';
import Topbar from './Topbar';
import Sidebar from './Sidebar';

export default function Layout() {
    return (
        <div className="min-h-screen bg-gray-50">
            <Topbar />

            <div className="pt-20 px-6">
                <div className="max-w-[1600px] mx-auto grid grid-cols-[240px_1fr] gap-4">
                    <div className="sticky top-20 self-start">
                        <Sidebar />
                    </div>

                    {/* ✅ la pagina può scrollare normalmente */}
                    <main className="min-w-0">
                        <Outlet />
                    </main>
                </div>
            </div>
        </div>
    );
}