export default function KPICard({ title, value, loading = false }) {
    // ✅ FIX: Gestisce oggetti inaspettati
    let displayValue = value;

    if (value && typeof value === 'object') {
        console.warn(`⚠️ KPICard "${title}" received object:`, value);
        displayValue = value.count || value.total || value.name || '?';
    }

    return (
        <div className="bg-[#f8f9ff] border border-[var(--border)] rounded-2xl p-4 min-h-[90px] flex flex-col justify-between">
            <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wide">
                {title}
            </h3>
            <div className="text-3xl font-extrabold mt-2">
                {loading ? (
                    <span className="text-gray-400 animate-pulse">···</span>
                ) : (
                    displayValue ?? '—'
                )}
            </div>
        </div>
    );
}