import { useState } from 'react';
import { useCreateProject } from '../../api/queries';
import Modal from '../ui/Modal';
import Input from '../ui/Input';
import Select from '../ui/Select';
import Button from '../ui/Button';
import AddressAutocomplete from '../ui/AddressAutocomplete';
import { toast } from '../ui/Toast';

export default function CreateProjectModal({ isOpen, onClose }) {
    const [formData, setFormData] = useState({
        name: '',
        // Address fields
        address_search: '',
        street: '',
        street_number: '',
        city: '',
        state: '',
        postal_code: '',
        formatted: '',
        // Dates
        start_date_estimated: '',
        end_date_estimated: '',
        status: 'Preventivo',
    });
    const [errors, setErrors] = useState({});

    const createMutation = useCreateProject();

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        if (errors[name]) {
            setErrors(prev => ({ ...prev, [name]: '' }));
        }
    };

    const handleAddressSelect = (address) => {
        setFormData(prev => ({
            ...prev,
            street: address.street || '',
            street_number: address.street_number || '',
            city: address.city || '',
            state: address.state || '',
            postal_code: address.postal_code || '',
            formatted: address.formatted || '',
        }));
    };

    const validate = () => {
        const newErrors = {};

        if (!formData.name.trim()) {
            newErrors.name = 'Il nome è obbligatorio';
        }

        if (formData.status === 'Confermato') {
            if (!formData.start_date_estimated) {
                newErrors.start_date_estimated = 'Obbligatorio per cantieri confermati';
            }
            if (!formData.end_date_estimated) {
                newErrors.end_date_estimated = 'Obbligatorio per cantieri confermati';
            }
        }

        if (formData.start_date_estimated && formData.end_date_estimated) {
            const start = new Date(formData.start_date_estimated);
            const end = new Date(formData.end_date_estimated);
            if (end < start) {
                newErrors.end_date_estimated = 'La data di fine non può precedere quella di inizio';
            }
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
                status: formData.status,
                city: formData.city.trim() || undefined,
                start_date_estimated: formData.start_date_estimated || null,
                end_date_estimated: formData.end_date_estimated || null,
                // Include full address if available
                address: formData.formatted ? {
                    formatted: formData.formatted,
                    street: formData.street || null,
                    street_number: formData.street_number || null,
                    city: formData.city || null,
                    state: formData.state || null,
                    postal_code: formData.postal_code || null,
                } : undefined,
            };

            await createMutation.mutateAsync(payload);
            toast(`Cantiere "${formData.name}" creato con successo`, 'success');

            // Reset form
            setFormData({
                name: '',
                address_search: '',
                street: '',
                street_number: '',
                city: '',
                state: '',
                postal_code: '',
                formatted: '',
                start_date_estimated: '',
                end_date_estimated: '',
                status: 'Preventivo',
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
            address_search: '',
            street: '',
            street_number: '',
            city: '',
            state: '',
            postal_code: '',
            formatted: '',
            start_date_estimated: '',
            end_date_estimated: '',
            status: 'Preventivo',
        });
        setErrors({});
        onClose();
    };

    return (
        <Modal isOpen={isOpen} onClose={handleClose} title="Nuovo cantiere" size="lg">
            <form onSubmit={handleSubmit} className="space-y-4">
                <Input
                    label="Nome cantiere"
                    name="name"
                    value={formData.name}
                    onChange={handleChange}
                    error={errors.name}
                    required
                    placeholder="Es: Ristrutturazione Villa Roma"
                />

                {/* Geoapify Autocomplete */}
                <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-gray-700">
                        Cerca indirizzo
                    </label>
                    <AddressAutocomplete
                        onAddressSelect={handleAddressSelect}
                        initialValue={formData.address_search}
                    />
                    <p className="text-xs text-[var(--muted)]">
                        Inizia a digitare per cercare l'indirizzo (min. 3 caratteri)
                    </p>
                </div>

                {/* Manual Address Fields */}
                <div className="grid grid-cols-2 gap-4">
                    <Input
                        label="Via"
                        name="street"
                        value={formData.street}
                        onChange={handleChange}
                        placeholder="Es: Via Dante"
                    />

                    <Input
                        label="Numero civico"
                        name="street_number"
                        value={formData.street_number}
                        onChange={handleChange}
                        placeholder="Es: 20"
                    />
                </div>

                <div className="grid grid-cols-3 gap-4">
                    <Input
                        label="Città"
                        name="city"
                        value={formData.city}
                        onChange={handleChange}
                        placeholder="Es: Firenze"
                    />

                    <Input
                        label="Stato"
                        name="state"
                        value={formData.state}
                        onChange={handleChange}
                        placeholder="Es: Italia"
                    />

                    <Input
                        label="CAP"
                        name="postal_code"
                        value={formData.postal_code}
                        onChange={handleChange}
                        placeholder="Es: 50122"
                    />
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <Input
                        label="Data inizio (stima)"
                        name="start_date_estimated"
                        type="date"
                        value={formData.start_date_estimated}
                        onChange={handleChange}
                        error={errors.start_date_estimated}
                        required={formData.status === 'Confermato'}
                    />

                    <Input
                        label="Data fine (stima)"
                        name="end_date_estimated"
                        type="date"
                        value={formData.end_date_estimated}
                        onChange={handleChange}
                        error={errors.end_date_estimated}
                        required={formData.status === 'Confermato'}
                    />
                </div>

                <Select
                    label="Stato"
                    name="status"
                    value={formData.status}
                    onChange={handleChange}
                    options={[
                        { value: 'Preventivo', label: 'Preventivo (Da approvare)' },
                        { value: 'Confermato', label: 'Confermato' },
                    ]}
                />

                {formData.status === 'Confermato' && (
                    <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 text-sm text-blue-800">
                        ℹ️ Per cantieri confermati, le date di inizio e fine sono obbligatorie
                    </div>
                )}

                <div className="flex justify-end gap-2 pt-4">
                    <Button type="button" onClick={handleClose}>
                        Annulla
                    </Button>
                    <Button type="submit" variant="primary" disabled={createMutation.isPending}>
                        {createMutation.isPending ? 'Creazione...' : 'Crea cantiere'}
                    </Button>
                </div>
            </form>
        </Modal>
    );
}