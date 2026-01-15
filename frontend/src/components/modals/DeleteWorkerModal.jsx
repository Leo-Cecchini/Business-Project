import { useState } from 'react';
import { useDeleteWorker } from '../../api/queries';
import Modal from '../ui/Modal';
import Input from '../ui/Input';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

export default function DeleteWorkerModal({ isOpen, onClose }) {
    const [workerId, setWorkerId] = useState('');
    const deleteMutation = useDeleteWorker();

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!workerId.trim()) {
            toast('Inserisci un ID operaio valido', 'error');
            return;
        }

        try {
            await deleteMutation.mutateAsync(workerId.trim());
            toast(`Operaio ${workerId} rimosso`, 'success');
            setWorkerId('');
            onClose();
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleClose = () => {
        setWorkerId('');
        onClose();
    };

    return (
        <Modal isOpen={isOpen} onClose={handleClose} title="Rimuovi operaio" size="sm">
            <form onSubmit={handleSubmit} className="space-y-4">
                <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-800">
                    ⚠️ Questa azione è irreversibile
                </div>

                <Input
                    label="ID Operaio"
                    value={workerId}
                    onChange={(e) => setWorkerId(e.target.value)}
                    placeholder="Es: W-1048"
                    required
                />

                <div className="flex justify-end gap-2 pt-4">
                    <Button type="button" onClick={handleClose}>
                        Annulla
                    </Button>
                    <Button type="submit" variant="danger" disabled={deleteMutation.isPending}>
                        {deleteMutation.isPending ? 'Rimozione...' : 'Rimuovi operaio'}
                    </Button>
                </div>
            </form>
        </Modal>
    );
}