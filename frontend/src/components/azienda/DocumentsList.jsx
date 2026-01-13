import { useRef } from 'react';
import { useCompanyDocuments, useUploadCompanyDocument } from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

export default function DocumentsList({ compact = false }) {
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

        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    // ✅ in sidebar mostriamo meno elementi (puoi cambiare 6)
    const visibleDocs = compact ? documents.slice(0, 6) : documents;

    return (
        <Card className={compact ? 'p-3' : undefined}>
            <div className="flex items-center justify-between gap-2">
                <h2
                    className={`${compact ? 'text-sm' : 'text-xl'} font-bold ${compact ? 'mb-0' : 'mb-2'
                        }`}
                >
                    Documenti aziendali
                </h2>

                {/* ✅ bottone più compatto in sidebar */}
                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.txt,.md"
                    onChange={handleUpload}
                    className="hidden"
                />

                <div className={compact ? '' : 'mb-0'}>
                    <Button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploadMutation.isPending}
                        className={compact ? 'px-2 py-1 text-xs rounded-lg' : undefined}
                    >
                        📥 {uploadMutation.isPending ? '...' : compact ? 'Carica' : 'Carica documenti'}
                    </Button>
                </div>
            </div>

            {!compact && (
                <p className="text-sm text-[var(--muted)] mb-4">
                    Documenti dell'azienda, consultabili da tutti i cantieri.
                </p>
            )}

            {/* ✅ lista più compatta + scroll in sidebar */}
            <div
                className={`${compact ? 'mt-2' : ''} ${compact ? 'space-y-1 max-h-44 overflow-auto pr-1' : 'space-y-2'
                    }`}
            >
                {isLoading ? (
                    <p className="text-sm text-[var(--muted)]">Caricamento...</p>
                ) : documents.length === 0 ? (
                    <p className="text-sm text-[var(--muted)]">Nessun documento caricato</p>
                ) : (
                    visibleDocs.map((doc, idx) => (
                        <div
                            key={idx}
                            className={`flex items-center gap-2 border border-[var(--border)] rounded-lg text-sm ${compact ? 'px-2 py-1' : 'p-2'
                                }`}
                            title={doc.name || doc}
                        >
                            <span className={compact ? 'text-xs' : ''}>📄</span>
                            <span className={compact ? 'text-xs truncate' : ''}>
                                {doc.name || doc}
                            </span>
                        </div>
                    ))
                )}
            </div>

            {/* ✅ se in compact tagli la lista, mostra indicazione */}
            {compact && documents.length > 6 && (
                <p className="mt-2 text-xs text-[var(--muted)]">
                    Mostro 6 di {documents.length} documenti
                </p>
            )}
        </Card>
    );
}