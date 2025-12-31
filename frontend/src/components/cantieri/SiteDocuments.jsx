import { useRef } from 'react';
import { useProjectDocuments, useUploadProjectDocument } from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

export default function SiteDocuments({ projectId }) {
    const fileInputRef = useRef(null);
    const { data, isLoading } = useProjectDocuments(projectId);
    const uploadMutation = useUploadProjectDocument();

    const documents = data?.documents || [];

    const handleUpload = async (e) => {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;

        for (const file of files) {
            try {
                await uploadMutation.mutateAsync({ projectId, file });
                toast(`File "${file.name}" caricato`, 'success');
            } catch (error) {
                toast(`Errore: ${error.message}`, 'error');
            }
        }

        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    return (
        <Card>
            <h3 className="text-lg font-bold mb-2">Documenti cantiere</h3>
            <p className="text-sm text-[var(--muted)] mb-4">
                Carica/consulta i documenti del cantiere selezionato.
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
                    <p className="text-sm text-[var(--muted)]">Nessun documento</p>
                ) : (
                    documents.map((doc, idx) => (
                        <div
                            key={idx}
                            className="flex items-center gap-2 p-2 border border-[var(--border)] rounded-lg text-sm"
                        >
                            📄 {doc.name || doc.path || doc}
                        </div>
                    ))
                )}
            </div>
        </Card>
    );
}