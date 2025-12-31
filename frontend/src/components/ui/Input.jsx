export default function Input({
    label,
    error,
    required = false,
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
            <input
                className={`px-3 py-2 border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)] ${error ? 'border-red-500' : 'border-[var(--border)]'
                    } ${className}`}
                {...props}
            />
            {error && <span className="text-xs text-red-600">{error}</span>}
        </div>
    );
}