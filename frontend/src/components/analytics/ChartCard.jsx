import { Line, Bar } from 'react-chartjs-2';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import Card from '../ui/Card';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    Filler
);

export default function ChartCard({ title, type = 'line', data, options = {}, loading = false }) {
    const defaultOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'top',
            },
        },
        scales: {
            y: {
                beginAtZero: true,
                ticks: {
                    precision: 0,
                },
            },
        },
        ...options,
    };

    const ChartComponent = type === 'bar' ? Bar : Line;

    const hasData = data && data.labels && data.labels.length > 0;

    return (
        <Card className="h-80">
            <h3 className="text-lg font-semibold mb-4">{title}</h3>
            <div className="h-64">
                {loading ? (
                    <div className="flex items-center justify-center h-full">
                        <div className="text-[var(--muted)] animate-pulse">
                            Caricamento...
                        </div>
                    </div>
                ) : hasData ? (
                    <ChartComponent data={data} options={defaultOptions} />
                ) : (
                    <div className="flex flex-col items-center justify-center h-full text-center px-4">
                        <p className="text-[var(--muted)] mb-2">
                            Nessun dato disponibile
                        </p>
                        <p className="text-xs text-[var(--muted)]">
                            Genera un report per visualizzare i grafici
                        </p>
                    </div>
                )}
            </div>
        </Card>
    );
}