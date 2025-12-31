import { mockFetch, USE_MOCK_DATA } from '../mocks/mockApi';

const API_BASE = import.meta.env.VITE_API_BASE || '';

export async function fetchAPI(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;

    const config = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
        ...options,
    };

    try {
        // Usa mockFetch se i mock sono abilitati
        const fetchFn = USE_MOCK_DATA ? mockFetch : fetch;
        const response = await fetchFn(url, config);

        const contentType = response.headers.get('content-type');
        let data;

        if (contentType?.includes('application/json')) {
            data = await response.json();
        } else {
            data = await response.text();
        }

        if (!response.ok) {
            throw new Error(data?.error || data || `HTTP ${response.status}`);
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

export const getAPI = (endpoint) => fetchAPI(endpoint);
export const postAPI = (endpoint, data) =>
    fetchAPI(endpoint, {
        method: 'POST',
        body: JSON.stringify(data),
    });
export const patchAPI = (endpoint, data) =>
    fetchAPI(endpoint, {
        method: 'PATCH',
        body: JSON.stringify(data),
    });
export const deleteAPI = (endpoint) =>
    fetchAPI(endpoint, { method: 'DELETE' });
