import { useState, useRef } from 'react';
import {
    useUploadComputo,
    useGenerateComputo,
} from '../../api/queries';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

export default function ComputoCard({ projectId, project }) {
    const fileInputRef = useRef(null);
    const [description, setDescription] = useState('');
    const [pdfUrl, setPdfUrl] = useState('');

    const uploadMutation = useUploadComputo();
    const generateMutation = useGenerateComputo();

    const handleUploadPDF = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        if (!file.name.toLowerCase().endsWith('.pdf')) {
            toast('Seleziona un file PDF valido', 'error');
            return;
        }

        try {
            await uploadMutation.mutateAsync({ projectId, file });
            toast('Computo metrico caricato e analizzato!', 'success');
            setPdfUrl('');

            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleGenerateComputo = async () => {
        if (description.trim().length < 10) {
            toast('Inserisci una descrizione di almeno 10 caratteri', 'error');
            return;
        }

        try {
            const result = await generateMutation.mutateAsync({
                projectId,
                description: description.trim()
            });

            toast('Computo metrico generato!', 'success');

            if (result.pdf_report_url) {
                setPdfUrl(result.pdf_report_url);
            }

            setDescription('');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    return (
        <div className="space-y-4">
            {/* Upload PDF */}
            <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Carica Computo da PDF
                </label>
                <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf"
                    onChange={handleUploadPDF}
                    className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-medium file:bg-[#eef2ff] file:text-gray-900 hover:file:bg-[#dbeafe] cursor-pointer"
                />
            </div>

            <div className="relative">
                <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-[var(--border)]"></div>
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-white px-2 text-[var(--muted)]">Oppure</span>
                </div>
            </div>

            {/* Generate from Text */}
            <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Genera Computo da Testo
                </label>
                <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={3}
                    placeholder="Es: Ristrutturazione bagno 6mq, rimozione piastrelle, rifacimento impianti..."
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)] resize-none"
                />
                <Button
                    variant="primary"
                    onClick={handleGenerateComputo}
                    disabled={generateMutation.isPending}
                    className="mt-2 w-full"
                >
                    {generateMutation.isPending ? 'Generazione...' : 'Genera Computo'}
                </Button>
            </div>
        </div>
    );
}