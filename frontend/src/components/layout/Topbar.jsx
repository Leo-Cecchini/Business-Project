import ProjectSelector from '../ui/ProjectSelector';

export default function Topbar() {
    return (
        <div className="bg-white border-b border-[var(--border)] px-4 py-3 sticky top-0 z-10">
            <div className="max-w-7xl mx-auto flex items-center justify-between">
                <div className="flex-1" />
                <h1 className="text-xl font-bold text-center flex-1">
                    🤖 Virtual Assistant
                </h1>
                <div className="flex-1 flex justify-end items-center gap-3">
                    <label className="text-sm text-[var(--muted)]">Cantiere:</label>
                    <ProjectSelector />
                </div>
            </div>
        </div>
    );
}