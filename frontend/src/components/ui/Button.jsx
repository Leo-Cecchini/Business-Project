export default function Button({
    children,
    onClick,
    variant = 'default',
    disabled = false,
    type = 'button',
    className = '',
}) {
    const baseClasses = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed';

    const variants = {
        default: 'bg-[#eef2ff] text-gray-900 border border-[var(--border)] hover:bg-[#dbeafe]',
        primary: 'bg-[var(--brand)] text-white hover:bg-[#2f4acc]',
        danger: 'bg-red-50 text-red-900 border border-red-200 hover:bg-red-100',
        ghost: 'bg-white border border-dashed border-[var(--border)] hover:bg-gray-50',
    };

    return (
        <button
            type={type}
            onClick={onClick}
            disabled={disabled}
            className={`${baseClasses} ${variants[variant]} ${className}`}
        >
            {children}
        </button>
    );
}