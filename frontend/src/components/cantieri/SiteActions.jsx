import { useApp } from '../../context/AppContext';
import { useProject } from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

export default function SiteActions() {
    const { selectedProjectId } = useApp();
    const { data: project } = useProject(selectedProjectId);

    // Fix: check computo_metrico
    const hasComputo = project?.meta_extra?.computo_metrico?.bill_of_quantities ||
        project?.meta_extra?.computo?.bill_of_quantities ||
        project?.computo?.bill_of_quantities;

    const handleDownloadPDF = async () => {
        if (!selectedProjectId || !hasComputo) {
            toast('Nessun computo disponibile per generare il PDF', 'error');
            return;
        }

        try {
            toast('Generazione PDF in corso...', 'info');

            await new Promise(resolve => setTimeout(resolve, 1500));

            const link = document.createElement('a');
            link.href = '/mock-computo.pdf';
            link.download = `computo-${selectedProjectId}-${Date.now()}.pdf`;
            link.click();

            toast('PDF scaricato con successo', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    if (!selectedProjectId) {
        return null;
    }

    return (
        <Card className="p-3">
            <h3 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wide mb-3">
                Azioni
            </h3>
            <Button
                onClick={handleDownloadPDF}
                disabled={!hasComputo}
                className="w-full justify-center"
                title={!hasComputo ? 'Genera prima un computo' : 'Scarica PDF del computo'}
            >
                📥 Scarica PDF Computo
            </Button>
            {!hasComputo && (
                <p className="text-xs text-[var(--muted)] mt-2 text-center">
                    Genera un computo per scaricare il PDF
                </p>
            )}
        </Card>
    );
}