import { useState, useEffect, useRef } from 'react';
import { geoapifyAutocomplete, formatAddress, isGeoapifyEnabled } from '../../utils/geoapify';

export default function AddressAutocomplete({ onAddressSelect, initialValue = '' }) {
    const [query, setQuery] = useState(initialValue);
    const [suggestions, setSuggestions] = useState([]);
    const [isOpen, setIsOpen] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const timeoutRef = useRef(null);
    const wrapperRef = useRef(null);

    // Close suggestions when clicking outside
    useEffect(() => {
        function handleClickOutside(event) {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        }

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        // Clear timeout on unmount
        return () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current);
            }
        };
    }, []);

    const handleInputChange = (e) => {
        const value = e.target.value;
        setQuery(value);

        // Clear previous timeout
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
        }

        // Don't search if query is too short
        if (value.trim().length < 3) {
            setSuggestions([]);
            setIsOpen(false);
            return;
        }

        // Debounce search
        setIsLoading(true);
        timeoutRef.current = setTimeout(async () => {
            try {
                const results = await geoapifyAutocomplete(value);
                setSuggestions(results);
                setIsOpen(results.length > 0);
            } catch (error) {
                console.error('Autocomplete error:', error);
                setSuggestions([]);
            } finally {
                setIsLoading(false);
            }
        }, 300);
    };

    const handleSelect = (suggestion) => {
        const formatted = suggestion.formatted || [
            suggestion.street,
            suggestion.housenumber,
            suggestion.postcode,
            suggestion.city,
            suggestion.country
        ].filter(Boolean).join(' ');

        setQuery(formatted);
        setIsOpen(false);
        setSuggestions([]);

        // Pass formatted address to parent
        if (onAddressSelect) {
            onAddressSelect(formatAddress(suggestion));
        }
    };

    if (!isGeoapifyEnabled()) {
        return (
            <div className="text-sm text-[var(--muted)] p-2 border border-[var(--border)] rounded-xl bg-gray-50">
                ℹ️ Autocomplete indirizzi non disponibile. Configura VITE_GEOAPIFY_KEY per abilitarlo.
            </div>
        );
    }

    return (
        <div ref={wrapperRef} className="relative">
            <input
                type="text"
                value={query}
                onChange={handleInputChange}
                placeholder="Es: Via Dante 20, Firenze"
                className="w-full px-3 py-2 border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
            />

            {isLoading && (
                <div className="absolute right-3 top-2.5 text-xs text-[var(--muted)]">
                    Ricerca...
                </div>
            )}

            {isOpen && suggestions.length > 0 && (
                <div className="absolute z-50 w-full mt-1 bg-white border border-[var(--border)] rounded-xl shadow-lg max-h-60 overflow-auto">
                    <ul className="py-1">
                        {suggestions.map((suggestion, idx) => {
                            const displayText = suggestion.formatted || [
                                suggestion.street,
                                suggestion.housenumber,
                                suggestion.postcode,
                                suggestion.city,
                                suggestion.country
                            ].filter(Boolean).join(' ');

                            return (
                                <li
                                    key={idx}
                                    onClick={() => handleSelect(suggestion)}
                                    className="px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm transition-colors"
                                >
                                    {displayText}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}
        </div>
    );
}