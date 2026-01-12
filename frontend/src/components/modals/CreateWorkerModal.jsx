import { useState } from 'react';
import { useCreateWorker } from '../../api/queries';
import Modal from '../ui/Modal';
import Input from '../ui/Input';
import Select from '../ui/Select';
import Button from '../ui/Button';
import { toast } from '../ui/Toast';

const ROLES = [
    'Operaio edile',
    'Muratore',
    'Carpentiere',
    'Ferraiolo',
    'Piastrellista',
    'Imbianchino',
    'Cartongessista',
    'Capo cantiere',
    'Elettricista',
    'Idraulico',
    'Termoidraulico',
    'Geometra',
];

const CITIES = [
    'Roma', 'Milano', 'Napoli', 'Torino', 'Palermo', 'Genova',
    'Bologna', 'Firenze', 'Bari', 'Catania', 'Venezia', 'Verona',
];

const CITY_TO_REGION = {
    Roma: 'Lazio',
    Milano: 'Lombardia',
    Napoli: 'Campania',
    Torino: 'Piemonte',
    Palermo: 'Sicilia',
    Genova: 'Liguria',
    Bologna: 'Emilia-Romagna',
    Firenze: 'Toscana',
    Bari: 'Puglia',
    Catania: 'Sicilia',
    Venezia: 'Veneto',
    Verona: 'Veneto',
};

export default function CreateWorkerModal({ isOpen, onClose }) {
    const [formData, setFormData] = useState({
        name: '',
        role: 'Operaio edile',
        hourly_rate: '',
        home_city: 'Roma',
        home_region: CITY_TO_REGION['Roma'] || '',
        is_active: true,
    });
    const [errors, setErrors] = useState({});

    const createMutation = useCreateWorker();

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => {
            const next = {
                ...prev,
                [name]: type === 'checkbox' ? checked : value,
            };
            if (name === 'home_city') {
                next.home_region = CITY_TO_REGION[value] || '';
            }
            return next;
        });
        if (errors[name]) {
            setErrors(prev => ({ ...prev, [name]: '' }));
        }
    };

    const validate = () => {
        const newErrors = {};

        if (!formData.name.trim()) {
            newErrors.name = 'Il nome è obbligatorio';
        }

        const rate = parseFloat(formData.hourly_rate);
        if (!formData.hourly_rate || isNaN(rate) || rate <= 0) {
            newErrors.hourly_rate = 'Inserisci una tariffa valida';
        }

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!validate()) return;

        try {
            const payload = {
                name: formData.name.trim(),
                role: formData.role,
                hourly_rate: parseFloat(formData.hourly_rate),
                home_city: formData.home_city,
                home_region: formData.home_region,
                is_active: formData.is_active,
            };

            await createMutation.mutateAsync(payload);
            toast(`Operaio "${formData.name}" aggiunto`, 'success');

            // Reset
            setFormData({
                name: '',
                role: 'Operaio edile',
                hourly_rate: '',
                home_city: 'Roma',
                home_region: CITY_TO_REGION['Roma'] || '',
                is_active: true,
            });
            setErrors({});
            onClose();
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleClose = () => {
        setFormData({
            name: '',
            role: 'Operaio edile',
            hourly_rate: '',
            home_city: 'Roma',
            home_region: CITY_TO_REGION['Roma'] || '',
            is_active: true,
        });
        setErrors({});
        onClose();
    };

    return (
        <Modal isOpen={isOpen} onClose={handleClose} title="Nuovo operaio">
            <form onSubmit={handleSubmit} className="space-y-4">
                <Input
                    label="Nome completo"
                    name="name"
                    value={formData.name}
                    onChange={handleChange}
                    error={errors.name}
                    required
                    placeholder="Es: Mario Rossi"
                />

                <Select
                    label="Ruolo principale"
                    name="role"
                    value={formData.role}
                    onChange={handleChange}
                    options={ROLES.map(r => ({ value: r, label: r }))}
                    required
                />

                <Input
                    label="Tariffa oraria (€)"
                    name="hourly_rate"
                    type="number"
                    step="0.01"
                    min="0"
                    value={formData.hourly_rate}
                    onChange={handleChange}
                    error={errors.hourly_rate}
                    required
                    placeholder="Es: 25.00"
                />

                <Select
                    label="Città base"
                    name="home_city"
                    value={formData.home_city}
                    onChange={handleChange}
                    options={CITIES.map(c => ({ value: c, label: c }))}
                    required
                />

                <Input
                    label="Regione"
                    name="home_region"
                    value={formData.home_region}
                    readOnly
                />

                <div className="flex items-center gap-3 p-3 border border-[var(--border)] rounded-xl">
                    <input
                        type="checkbox"
                        name="is_active"
                        id="is_active"
                        checked={formData.is_active}
                        onChange={handleChange}
                        className="w-4 h-4"
                    />
                    <label htmlFor="is_active" className="text-sm font-medium cursor-pointer">
                        Disponibile per assegnazione
                    </label>
                </div>

                <div className="flex justify-end gap-2 pt-4">
                    <Button type="button" onClick={handleClose}>
                        Annulla
                    </Button>
                    <Button type="submit" variant="primary" disabled={createMutation.isPending}>
                        {createMutation.isPending ? 'Salvataggio...' : 'Salva operaio'}
                    </Button>
                </div>
            </form>
        </Modal>
    );
}