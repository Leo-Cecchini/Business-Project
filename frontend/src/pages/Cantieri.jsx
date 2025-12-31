import { Outlet } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useProjects } from '../api/queries';
import SitesList from '../components/cantieri/SitesList';
import SiteSidebar from '../components/cantieri/SiteSidebar';
import SiteActions from '../components/cantieri/SiteActions';

export default function Cantieri() {
  const { selectedProjectId, selectProject } = useApp();
  const { data: projects = [] } = useProjects();

  return (
    <div className="grid grid-cols-[1fr_320px] gap-4">
      {/* Contenuto principale */}
      <div className="min-w-0">
        <Outlet />
      </div>

      {/* Sidebar destra: Lista + Gestione + Azioni - sticky */}
      <div className="space-y-4 sticky top-20 self-start">
        <SitesList
          projects={projects}
          selectedId={selectedProjectId}
          onSelect={selectProject}
        />

        <SiteSidebar />

        <SiteActions />
      </div>
    </div>
  );
}