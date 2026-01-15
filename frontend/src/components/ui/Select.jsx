export default function Select({
    label,
    error,
    required = false,
    options = [],
    className = '',
    ...props
}) {
    return (
        <div className="flex flex-col gap-1.5">
            {label && (
                <label className="text-sm font-semibold text-gray-700">
                    {label}
                    {required && <span className="text-red-600 ml-1">*</span>}
                </label>
            )}
            <select
                className={`px-3 py-2 border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)] bg-white ${error ? 'border-red-500' : 'border-[var(--border)]'
                    } ${className}`}
                {...props}
            >
                {options.map((option) => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))}
            </select>
            {error && <span className="text-xs text-red-600">{error}</span>}
        </div>
    );
}