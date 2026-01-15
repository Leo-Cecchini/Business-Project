export default function Card({ children, className = '', ...props }) {
    return (
        <div
            {...props}
            className={`bg-white border border-[var(--border)] rounded-2xl p-5 shadow-sm min-h-0 ${className}`}
        >
            {children}
        </div>
    );
}