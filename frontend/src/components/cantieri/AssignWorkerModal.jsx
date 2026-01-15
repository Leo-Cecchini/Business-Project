import { useState, useEffect } from 'react';
import { useWorkers } from '../../api/queries';
import Modal from '../ui/Modal';
import Input from '../ui/Input';
import Select from '../ui/Select';
import Button from '../ui/Button';

export default function AssignWorkerModal({ isOpen, onClose, work, onAssign }) {
    const { data: workersData } = useWorkers();
    const [workerId, setWorkerId] = useState('');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');

    // ✅ Gestione robusta: workersData può essere array o {items: [...]}
    const workers = Array.isArray(workersData) 
        ? workersData 
        : (workersData?.items || []);
    
    // ✅ Filtro robusto: usa is_active O available
    const availableWorkers = workers.filter(w => w.is_active || w.available);

    // Debug log (rimuovi dopo test)
    console.log('AssignWorkerModal - workersData:', workersData);
    console.log('AssignWorkerModal - workers array:', workers);
    console.log('AssignWorkerModal - availableWorkers:', availableWorkers);

    // Auto-fill dates from work
    useEffect(() => {
        if (work) {
            setStartDate(work.start_date_planned || '');
            setEndDate(work.end_date_planned || '');
        }
    }, [work]);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!workerId) return;

        onAssign({
            workerId,
            startDate,
            endDate,
        });

        // Reset
        setWorkerId('');
        setStartDate('');
        setEndDate('');
    };

    const handleClose = () => {
        setWorkerId('');
        setStartDate('');
        setEndDate('');
        onClose();
    };

    if (!work) return null;

    return (
        <Modal isOpen={isOpen} onClose={handleClose} title="Assegna Operaio" size="md">
            <form onSubmit={handleSubmit} className="space-y-4">
                <div className="bg-blue-50 border border-blue-200 rounded-xl p-3">
                    <p className="text-sm font-semibold text-blue-800">
                        Lavoro: {work.work_name}
                    </p>
                </div>

                <Select
                    label="Operaio"
                    value={workerId}
                    onChange={(e) => setWorkerId(e.target.value)}
                    options={[
                        { value: '', label: '— Seleziona operaio —' },
                        ...availableWorkers.map(w => ({
                            value: w.id,
                            label: `${w.name} (${w.role || 'Operaio'})`,
                        })),
                    ]}
                    required
                />

                {availableWorkers.length === 0 && (
                    <p className="text-sm text-red-600">
                        Nessun operaio disponibile. Aggiungi operai dalla sezione Azienda.
                    </p>
                )}

                <div className="grid grid-cols-2 gap-4">
                    <Input
                        label="Data inizio"
                        type="date"
                        value={startDate}
                        onChange={(e) => setStartDate(e.target.value)}
                        required
                    />

                    <Input
                        label="Data fine"
                        type="date"
                        value={endDate}
                        onChange={(e) => setEndDate(e.target.value)}
                        required
                    />
                </div>

                <div className="flex justify-end gap-2 pt-4">
                    <Button type="button" onClick={handleClose}>
                        Annulla
                    </Button>
                    <Button type="submit" variant="primary" disabled={!workerId || availableWorkers.length === 0}>
                        Assegna
                    </Button>
                </div>
            </form>
        </Modal>
    );
}