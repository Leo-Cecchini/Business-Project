export default function Card({ children, className = '' }) {
    return (
        <div className={`bg-white border border-[var(--border)] rounded-2xl p-5 shadow-sm ${className}`}>
            {children}
        </div>
    );
}