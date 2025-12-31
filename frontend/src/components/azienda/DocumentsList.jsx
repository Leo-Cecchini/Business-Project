import { useRef } from 'react';
import { useCompanyDocuments, useUploadCompanyDocument } from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

export default function DocumentsList() {
    const fileInputRef = useRef(null);
    const { data, isLoading } = useCompanyDocuments();
    const uploadMutation = useUploadCompanyDocument();

    const documents = data?.documents || [];

    const handleUpload = async (e) => {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;

        for (const file of files) {
            try {
                await uploadMutation.mutateAsync(file);
                toast(`File "${file.name}" caricato con successo`, 'success');
            } catch (error) {
                toast(`Errore caricando ${file.name}: ${error.message}`, 'error');
            }
        }

        // Reset input
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    return (
        <Card>
            <h2 className="text-xl font-bold mb-2">Documenti aziendali</h2>
            <p className="text-sm text-[var(--muted)] mb-4">
                Documenti dell'azienda, consultabili da tutti i cantieri.
            </p>

            <div className="mb-4">
                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.txt,.md"
                    onChange={handleUpload}
                    className="hidden"
                />
                <Button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploadMutation.isPending}
                >
                    📥 {uploadMutation.isPending ? 'Caricamento...' : 'Carica documenti'}
                </Button>
            </div>

            <div className="space-y-2">
                {isLoading ? (
                    <p className="text-sm text-[var(--muted)]">Caricamento...</p>
                ) : documents.length === 0 ? (
                    <p className="text-sm text-[var(--muted)]">Nessun documento caricato</p>
                ) : (
                    documents.map((doc, idx) => (
                        <div
                            key={idx}
                            className="flex items-center gap-2 p-2 border border-[var(--border)] rounded-lg text-sm"
                        >
                            📄 {doc.name || doc}
                        </div>
                    ))
                )}
            </div>
        </Card>
    );
}