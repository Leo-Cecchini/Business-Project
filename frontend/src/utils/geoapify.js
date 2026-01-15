const GEOAPIFY_KEY = import.meta.env.VITE_GEOAPIFY_KEY || '';

export function isGeoapifyEnabled() {
    return Boolean(GEOAPIFY_KEY);
}

export async function geoapifyAutocomplete(query) {
    if (!GEOAPIFY_KEY || !query) return [];

    const url = `https://api.geoapify.com/v1/geocode/autocomplete?text=${encodeURIComponent(query)}&limit=7&lang=it&apiKey=${GEOAPIFY_KEY}`;

    try {
        const response = await fetch(url);
        if (!response.ok) return [];

        const data = await response.json();
        return (data.features || []).map(f => f.properties || {});
    } catch (error) {
        console.warn('[Geoapify] Error:', error);
        return [];
    }
}

export function formatAddress(props) {
    const street = props.street || props.name || '';
    const number = props.housenumber || '';
    const city = props.city || props.county || props.town || props.village || '';
    const state = props.country || props.state || '';
    const zip = props.postcode || '';

    const formatted = props.formatted || [
        [street, number].filter(Boolean).join(' '),
        [zip, city].filter(Boolean).join(' '),
        state
    ].filter(Boolean).join(', ');

    return {
        formatted: formatted || city || '',
        street: street || null,
        street_number: number || null,
        city: city || null,
        state: state || null,
        postal_code: zip || null,
    };
}