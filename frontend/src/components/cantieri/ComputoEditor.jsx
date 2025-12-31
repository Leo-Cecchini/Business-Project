import { useState, useEffect } from 'react';
import { useProject, useUpdateComputo } from '../../api/queries';
import Card from '../ui/Card';
import Button from '../ui/Button';
import Input from '../ui/Input';
import { toast } from '../ui/Toast';

export default function ComputoEditor({ projectId }) {
    const { data: project, refetch } = useProject(projectId);
    const updateComputoMutation = useUpdateComputo();  // ✅ Aggiungi mutation
    const [computoData, setComputoData] = useState(null);
    const [editingItem, setEditingItem] = useState(null);
    const [addingItem, setAddingItem] = useState(null);
    const [addingCategory, setAddingCategory] = useState(false);
    const [expandedCategories, setExpandedCategories] = useState(new Set());

    useEffect(() => {
        if (project) {
            // Fix: usa meta_extra.computo_metrico (non computo)
            const computo = project.meta_extra?.computo_metrico ||
                project.meta_extra?.computo ||
                project.computo ||
                null;

            // ✅ Trasforma da piatto a nested
            const transformed = transformComputoData(computo);
            setComputoData(transformed);

            if (transformed?.bill_of_quantities) {
                setExpandedCategories(new Set(
                    transformed.bill_of_quantities.map((_, idx) => idx)
                ));
            }
        }
    }, [project]);

    // ✅ Trasforma da formato piatto API a formato nested per il componente
    const transformComputoData = (computo) => {
        if (!computo || !computo.bill_of_quantities) return computo;

        // Se già nested (ha items), ritorna così
        if (computo.bill_of_quantities[0]?.items) {
            return computo;
        }

        // Trasforma da piatto a nested
        const grouped = {};

        computo.bill_of_quantities.forEach(item => {
            const categoryName = item.category;

            if (!grouped[categoryName]) {
                grouped[categoryName] = {
                    category: categoryName,
                    items: [],
                    category_total: 0
                };
            }

            // Aggiungi item alla categoria
            grouped[categoryName].items.push({
                ...item,
                item_total: item.total_price || (item.quantity * item.unit_price) || 0
            });
        });

        // Calcola totali categoria
        Object.values(grouped).forEach(category => {
            category.category_total = category.items.reduce(
                (sum, item) => sum + (item.item_total || 0),
                0
            );
        });

        // Ricrea struttura computo
        const transformed = {
            ...computo,
            bill_of_quantities: Object.values(grouped)
        };

        // Ricrea summary
        transformed.summary = transformed.bill_of_quantities.map(cat => ({
            category: cat.category,
            price: cat.category_total
        }));

        // Calcola grand total
        transformed.grand_total = transformed.summary.reduce(
            (sum, s) => sum + s.price,
            0
        );

        return transformed;
    };


    if (!computoData || !computoData.bill_of_quantities) {
        return (
            <Card>
                <div className="text-center py-8">
                    <p className="text-[var(--muted)] mb-4">
                        Nessun computo metrico disponibile
                    </p>
                    <p className="text-sm text-[var(--muted)]">
                        Carica un PDF o genera un computo da testo per iniziare
                    </p>
                </div>
            </Card>
        );
    }

    const toggleCategory = (idx) => {
        const newExpanded = new Set(expandedCategories);
        if (newExpanded.has(idx)) {
            newExpanded.delete(idx);
        } else {
            newExpanded.add(idx);
        }
        setExpandedCategories(newExpanded);
    };

    const recalculateTotals = (computo) => {
        computo.bill_of_quantities.forEach(category => {
            category.category_total = category.items.reduce((sum, item) => sum + (item.item_total || 0), 0);
        });

        computo.summary = computo.bill_of_quantities.map(cat => ({
            category: cat.category,
            price: cat.category_total,
        }));

        computo.grand_total = computo.summary.reduce((sum, s) => sum + s.price, 0);
    };

    // ✅ Salva computo usando mutation
    const saveComputo = async (projectId, computo) => {
        try {
            await updateComputoMutation.mutateAsync({
                projectId,
                computo
            });
            await refetch();  // Ricarica progetto
            return true;
        } catch (error) {
            console.error('Error saving computo:', error);
            throw error;
        }
    };

    const handleDeleteItem = async (categoryIdx, itemIdx) => {
        if (!window.confirm('Eliminare questa voce dal computo?')) return;

        const newComputo = { ...computoData };
        const category = newComputo.bill_of_quantities[categoryIdx];

        category.items.splice(itemIdx, 1);

        if (category.items.length === 0) {
            newComputo.bill_of_quantities.splice(categoryIdx, 1);
        }

        recalculateTotals(newComputo);

        try {
            await saveComputo(projectId, newComputo);
            setComputoData(newComputo);
            toast('Voce eliminata', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleDeleteCategory = async (categoryIdx) => {
        const category = computoData.bill_of_quantities[categoryIdx];
        if (!window.confirm(`Eliminare l'intera categoria "${category.category}" con ${category.items.length} voci?`)) return;

        const newComputo = { ...computoData };
        newComputo.bill_of_quantities.splice(categoryIdx, 1);

        recalculateTotals(newComputo);

        try {
            await saveComputo(projectId, newComputo);
            setComputoData(newComputo);
            toast('Categoria eliminata', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleEditItem = (categoryIdx, itemIdx) => {
        const item = computoData.bill_of_quantities[categoryIdx].items[itemIdx];
        setEditingItem({
            categoryIdx,
            itemIdx,
            data: { ...item },
        });
    };

    const handleSaveEdit = async () => {
        if (!editingItem) return;

        const newComputo = { ...computoData };
        const category = newComputo.bill_of_quantities[editingItem.categoryIdx];

        const quantity = parseFloat(editingItem.data.quantity) || 0;
        const unitPrice = parseFloat(editingItem.data.unit_price) || 0;
        editingItem.data.item_total = quantity * unitPrice;

        category.items[editingItem.itemIdx] = editingItem.data;

        recalculateTotals(newComputo);

        try {
            await saveComputo(projectId, newComputo);
            setComputoData(newComputo);
            setEditingItem(null);
            toast('Voce aggiornata', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleAddCategory = () => {
        setAddingCategory(true);
    };

    const handleSaveNewCategory = async (categoryName) => {
        if (!categoryName.trim()) {
            toast('Inserisci un nome per la categoria', 'error');
            return;
        }

        const newComputo = { ...computoData };
        newComputo.bill_of_quantities.push({
            category: categoryName.trim(),
            category_total: 0,
            items: [],
        });

        recalculateTotals(newComputo);

        try {
            await saveComputo(projectId, newComputo);
            setComputoData(newComputo);
            setAddingCategory(false);
            toast('Categoria aggiunta', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const handleAddItem = (categoryIdx) => {
        setAddingItem({
            categoryIdx,
            data: {
                reference: '',
                code: '',
                description: '',
                quantity: 0,
                unit: '',
                unit_price: 0,
                item_total: 0,
            },
        });
    };

    const handleSaveNewItem = async () => {
        if (!addingItem) return;

        const newComputo = { ...computoData };
        const category = newComputo.bill_of_quantities[addingItem.categoryIdx];

        const quantity = parseFloat(addingItem.data.quantity) || 0;
        const unitPrice = parseFloat(addingItem.data.unit_price) || 0;
        addingItem.data.item_total = quantity * unitPrice;

        category.items.push(addingItem.data);

        recalculateTotals(newComputo);

        try {
            await saveComputo(projectId, newComputo);
            setComputoData(newComputo);
            setAddingItem(null);
            toast('Voce aggiunta', 'success');
        } catch (error) {
            toast(`Errore: ${error.message}`, 'error');
        }
    };

    const formatCurrency = (value) => {
        return new Intl.NumberFormat('it-IT', {
            style: 'currency',
            currency: 'EUR',
        }).format(value || 0);
    };

    return (
        <Card>
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-bold">Computo Metrico</h3>
                    <p className="text-sm text-[var(--muted)]">
                        {computoData.metadata?.subject || 'Bill of Quantities'}
                    </p>
                </div>
                <Button variant="primary" onClick={handleAddCategory}>
                    + Aggiungi Categoria
                </Button>
            </div>

            {/* Metadata */}
            {computoData.metadata && (
                <div className="bg-gray-50 rounded-xl p-4 mb-4 grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
                    {computoData.metadata.document_title && (
                        <div>
                            <span className="text-[var(--muted)]">Titolo:</span>
                            <p className="font-medium">{computoData.metadata.document_title}</p>
                        </div>
                    )}
                    {computoData.metadata.client && (
                        <div>
                            <span className="text-[var(--muted)]">Cliente:</span>
                            <p className="font-medium">{computoData.metadata.client}</p>
                        </div>
                    )}
                    {computoData.metadata.location && (
                        <div>
                            <span className="text-[var(--muted)]">Località:</span>
                            <p className="font-medium">{computoData.metadata.location}</p>
                        </div>
                    )}
                    {computoData.metadata.date && (
                        <div>
                            <span className="text-[var(--muted)]">Data:</span>
                            <p className="font-medium">{computoData.metadata.date}</p>
                        </div>
                    )}
                </div>
            )}

            {/* Bill of Quantities */}
            <div className="space-y-3">
                {computoData.bill_of_quantities.map((category, catIdx) => {
                    const isExpanded = expandedCategories.has(catIdx);

                    return (
                        <div key={catIdx} className="border border-[var(--border)] rounded-xl overflow-hidden">
                            <div className="bg-gray-50 p-4 flex items-center justify-between">
                                <button
                                    onClick={() => toggleCategory(catIdx)}
                                    className="flex items-center gap-2 flex-1 text-left"
                                >
                                    <span className="text-lg">
                                        {isExpanded ? '▼' : '▶'}
                                    </span>
                                    <div className="flex-1">
                                        <h4 className="font-bold text-sm">{category.category}</h4>
                                        <p className="text-xs text-[var(--muted)]">
                                            {category.items.length} voci • {formatCurrency(category.category_total)}
                                        </p>
                                    </div>
                                </button>
                                <div className="flex gap-2">
                                    <Button
                                        onClick={() => handleAddItem(catIdx)}
                                        className="!py-1 !px-2 text-xs"
                                    >
                                        + Aggiungi voce
                                    </Button>
                                    <Button
                                        variant="danger"
                                        onClick={() => handleDeleteCategory(catIdx)}
                                        className="!py-1 !px-2 text-xs"
                                    >
                                        Elimina categoria
                                    </Button>
                                </div>
                            </div>

                            {isExpanded && (
                                <div className="divide-y divide-[var(--border)]">
                                    {category.items.map((item, itemIdx) => (
                                        <div key={itemIdx} className="p-4 hover:bg-gray-50 transition-colors">
                                            <div className="flex items-start justify-between gap-4 mb-2">
                                                <div className="flex-1">
                                                    <div className="flex items-center gap-2 mb-1">
                                                        {item.reference && (
                                                            <span className="inline-flex items-center px-2 py-0.5 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                                                                {item.reference}
                                                            </span>
                                                        )}
                                                        {item.code && (
                                                            <span className="inline-flex items-center px-2 py-0.5 bg-gray-200 text-gray-800 rounded text-xs font-mono">
                                                                {item.code}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <p className="text-sm">{item.description}</p>
                                                </div>
                                                <div className="flex gap-1">
                                                    <Button
                                                        onClick={() => handleEditItem(catIdx, itemIdx)}
                                                        className="!py-1 !px-2 text-xs"
                                                    >
                                                        ✏️ Modifica
                                                    </Button>
                                                    <Button
                                                        variant="danger"
                                                        onClick={() => handleDeleteItem(catIdx, itemIdx)}
                                                        className="!py-1 !px-2 text-xs"
                                                    >
                                                        🗑️
                                                    </Button>
                                                </div>
                                            </div>

                                            <div className="grid grid-cols-4 gap-4 text-sm mt-2">
                                                <div>
                                                    <span className="text-xs text-[var(--muted)]">Quantità</span>
                                                    <p className="font-medium">
                                                        {item.quantity} {item.unit}
                                                    </p>
                                                </div>
                                                <div>
                                                    <span className="text-xs text-[var(--muted)]">Prezzo unitario</span>
                                                    <p className="font-medium">{formatCurrency(item.unit_price)}</p>
                                                </div>
                                                <div className="col-span-2">
                                                    <span className="text-xs text-[var(--muted)]">Totale</span>
                                                    <p className="font-bold text-lg">{formatCurrency(item.item_total)}</p>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Summary */}
            <div className="mt-6 bg-blue-50 border-2 border-blue-200 rounded-xl p-4">
                <h4 className="font-bold mb-3">Riepilogo</h4>
                <div className="space-y-2">
                    {computoData.summary?.map((item, idx) => (
                        <div key={idx} className="flex justify-between text-sm">
                            <span>{item.category}</span>
                            <span className="font-semibold">{formatCurrency(item.price)}</span>
                        </div>
                    ))}
                    <div className="border-t-2 border-blue-300 pt-2 mt-2 flex justify-between text-lg font-bold">
                        <span>TOTALE GENERALE</span>
                        <span className="text-[var(--brand)]">
                            {formatCurrency(computoData.grand_total)}
                        </span>
                    </div>
                </div>
            </div>

            {/* Edit Item Modal */}
            {editingItem && (
                <EditItemModal
                    item={editingItem}
                    onSave={handleSaveEdit}
                    onCancel={() => setEditingItem(null)}
                    onChange={(field, value) => {
                        setEditingItem({
                            ...editingItem,
                            data: { ...editingItem.data, [field]: value },
                        });
                    }}
                />
            )}

            {/* Add Item Modal */}
            {addingItem && (
                <EditItemModal
                    item={addingItem}
                    onSave={handleSaveNewItem}
                    onCancel={() => setAddingItem(null)}
                    onChange={(field, value) => {
                        setAddingItem({
                            ...addingItem,
                            data: { ...addingItem.data, [field]: value },
                        });
                    }}
                    title="Aggiungi Nuova Voce"
                />
            )}

            {/* Add Category Modal */}
            {addingCategory && (
                <AddCategoryModal
                    onSave={handleSaveNewCategory}
                    onCancel={() => setAddingCategory(false)}
                />
            )}
        </Card>
    );
}

// ... resto del codice (saveComputo, EditItemModal) ...

async function saveComputo(projectId, computoData) {
    const response = await fetch(`/api/projects/${projectId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            meta_extra: {
                computo_metrico: computoData, // Fix: usa computo_metrico
            },
        }),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to save computo');
    }

    return response.json();
}

function EditItemModal({ item, onSave, onCancel, onChange, title = 'Modifica Voce' }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50 backdrop-blur-sm animate-fade-in">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto animate-scale-in">
                <div className="p-5 border-b border-[var(--border)]">
                    <h3 className="text-xl font-bold">{title}</h3>
                </div>

                <div className="p-5 space-y-4">
                    <Input
                        label="Riferimento"
                        value={item.data.reference || ''}
                        onChange={(e) => onChange('reference', e.target.value)}
                    />

                    <Input
                        label="Codice"
                        value={item.data.code || ''}
                        onChange={(e) => onChange('code', e.target.value)}
                    />

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1.5">
                            Descrizione
                        </label>
                        <textarea
                            value={item.data.description || ''}
                            onChange={(e) => onChange('description', e.target.value)}
                            rows={3}
                            className="w-full px-3 py-2 border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)] resize-none"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <Input
                            label="Quantità"
                            type="number"
                            step="0.01"
                            value={item.data.quantity || ''}
                            onChange={(e) => onChange('quantity', e.target.value)}
                        />

                        <Input
                            label="Unità di misura"
                            value={item.data.unit || ''}
                            onChange={(e) => onChange('unit', e.target.value)}
                            placeholder="es: mq, ml, cad"
                        />
                    </div>

                    <Input
                        label="Prezzo unitario (€)"
                        type="number"
                        step="0.01"
                        value={item.data.unit_price || ''}
                        onChange={(e) => onChange('unit_price', e.target.value)}
                    />

                    <div className="bg-blue-50 border border-blue-200 rounded-xl p-3">
                        <p className="text-sm font-semibold text-blue-800">
                            Totale calcolato: €{' '}
                            {((parseFloat(item.data.quantity) || 0) * (parseFloat(item.data.unit_price) || 0)).toFixed(2)}
                        </p>
                    </div>
                </div>

                <div className="p-5 border-t border-[var(--border)] flex justify-end gap-2">
                    <Button onClick={onCancel}>Annulla</Button>
                    <Button variant="primary" onClick={onSave}>
                        Salva
                    </Button>
                </div>
            </div>
        </div>
    );
}

function AddCategoryModal({ onSave, onCancel }) {
    const [categoryName, setCategoryName] = useState('');

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50 backdrop-blur-sm animate-fade-in">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md animate-scale-in">
                <div className="p-5 border-b border-[var(--border)]">
                    <h3 className="text-xl font-bold">Aggiungi Categoria</h3>
                </div>

                <div className="p-5">
                    <Input
                        label="Nome Categoria"
                        value={categoryName}
                        onChange={(e) => setCategoryName(e.target.value)}
                        placeholder="es: DEMOLIZIONI E RIMOZIONI"
                        required
                    />
                </div>

                <div className="p-5 border-t border-[var(--border)] flex justify-end gap-2">
                    <Button onClick={onCancel}>Annulla</Button>
                    <Button variant="primary" onClick={() => onSave(categoryName)}>
                        Aggiungi
                    </Button>
                </div>
            </div>
        </div>
    );
}