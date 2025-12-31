import { useState, useRef } from 'react';
import { useApp } from '../context/AppContext';
import {
    useProject,
    useUploadComputo,
    useGenerateComputo,
} from '../api/queries';
import { useNavigate } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ComputoEditor from '../components/cantieri/ComputoEditor';
import { toast } from '../components/ui/Toast';

export default function CantieriComputo() {
    const { selectedProjectId } = useApp();
    const { data: currentProject } = useProject(selectedProjectId);
    const navigate = useNavigate();

    const fileInputRef = useRef(null);
    const [description, setDescription] = useState('');
    const [showGenerate, setShowGenerate] = useState(false);

    const uploadMutation = useUploadComputo();
    const generateMutation = useGenerateComputo();

    const hasComputo = currentProject?.meta_extra?.computo_metrico?.bill_of_quantities ||
        currentProject?.meta_extra?.computo?.bill_of_quantities ||
        currentProject?.computo?.bill_of_quantities;

    const handleUploadPDF = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        if (!file.name.toLowerCase().endsWith('.pdf')) {
            toast('Seleziona un file PDF valido', 'error');
            return;
        }

        try {
            await uploadMutation.mutateAsync({ projectId: selectedProjectId, file });
            toast('Computo metrico caricato e analizzato!', 'success');
            setShowGenerate(false);

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
            await generateMutation.mutateAsync({
                projectId: selectedProjectId,
                description: description.trim()
            });

            toast('Computo metrico generato!', 'success');
            setDescription('');
            setShowGenerate(false);
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    if (!selectedProjectId) {
        return (
            <Card>
                <div className="text-center py-12">
                    <p className="text-lg text-[var(--muted)] mb-4">
                        Nessun cantiere selezionato
                    </p>
                    <Button variant="primary" onClick={() => navigate('/cantieri')}>
                        ← Torna alla panoramica
                    </Button>
                </div>
            </Card>
        );
    }

    return (
        <div className="space-y-4">
            {/* Actions Header */}
            <Card>
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-bold">
                            {hasComputo ? 'Gestisci Computo Metrico' : 'Genera Computo Metrico'}
                        </h2>
                        <p className="text-sm text-[var(--muted)]">
                            {currentProject?.name || currentProject?.nome}
                        </p>
                    </div>
                    {hasComputo && (
                        <Button
                            variant="ghost"
                            onClick={() => setShowGenerate(!showGenerate)}
                        >
                            {showGenerate ? 'Nascondi' : '🔄 Sostituisci Computo'}
                        </Button>
                    )}
                </div>
            </Card>

            {/* Sezione Generazione/Sostituzione Computo */}
            {(!hasComputo || showGenerate) && (
                <Card>
                    <h3 className="text-lg font-bold mb-4">
                        {hasComputo ? 'Sostituisci Computo' : 'Genera Nuovo Computo'}
                    </h3>

                    {hasComputo && (
                        <div className="bg-orange-50 border border-orange-200 rounded-xl p-3 mb-4">
                            <p className="text-sm text-orange-800">
                                ⚠️ Attenzione: sostituendo il computo, quello attuale verrà sovrascritto
                            </p>
                        </div>
                    )}

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
                                disabled={uploadMutation.isPending}
                                className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-medium file:bg-[#eef2ff] file:text-gray-900 hover:file:bg-[#dbeafe] cursor-pointer disabled:opacity-50"
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
                                rows={4}
                                placeholder="Es: Ristrutturazione bagno 6mq, rimozione piastrelle, rifacimento impianti idraulici ed elettrici, posa nuovo pavimento..."
                                className="w-full px-3 py-2 border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)] resize-none"
                                disabled={generateMutation.isPending}
                            />
                            <Button
                                variant="primary"
                                onClick={handleGenerateComputo}
                                disabled={generateMutation.isPending}
                                className="mt-2 w-full"
                            >
                                {generateMutation.isPending ? 'Generazione in corso...' : 'Genera Computo'}
                            </Button>
                        </div>
                    </div>
                </Card>
            )}

            {/* Computo Editor - solo se esiste */}
            {hasComputo && !showGenerate && (
                <ComputoEditor projectId={selectedProjectId} />
            )}

            {/* Messaggio se nessun computo */}
            {!hasComputo && !showGenerate && (
                <Card>
                    <div className="text-center py-12">
                        <p className="text-lg text-[var(--muted)] mb-4">
                            Nessun computo metrico disponibile
                        </p>
                        <p className="text-sm text-[var(--muted)] mb-6">
                            Carica un PDF o genera un computo da testo per iniziare
                        </p>
                    </div>
                </Card>
            )}
        </div>
    );
}