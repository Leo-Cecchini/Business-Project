import { USE_MOCK_DATA, MOCK_DELAY } from './config';
import projectsData from './projects.json';

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// Storage in memoria - inizializza da projects.json
let mockStorage = {
    projects: JSON.parse(JSON.stringify(projectsData)), // Deep clone
    workers: [
        { id: 'W-1001', name: 'Mario Rossi', role: 'Muratore', hourly_rate: 25, home_city: 'Roma', is_active: true },
        { id: 'W-1002', name: 'Luigi Bianchi', role: 'Elettricista', hourly_rate: 30, home_city: 'Milano', is_active: true },
        { id: 'W-1003', name: 'Giuseppe Verdi', role: 'Idraulico', hourly_rate: 28, home_city: 'Firenze', is_active: true },
        { id: 'W-1004', name: 'Paolo Neri', role: 'Muratore', hourly_rate: 24, home_city: 'Firenze', is_active: true },
        { id: 'W-1005', name: 'Franco Blu', role: 'Piastrellista', hourly_rate: 27, home_city: 'Roma', is_active: true },
    ],
    companyDocuments: [
        { name: 'Listino_Prezzi_2025.pdf' },
        { name: 'Contratto_Tipo.pdf' },
        { name: 'Sicurezza_Cantiere.pdf' },
    ],
    projectDocuments: {
        'mock-1': [
            { name: 'Planimetria_Villa.pdf' },
            { name: 'Progetto_Esecutivo.pdf' },
        ],
        'mock-2': [
            { name: 'Computo_Uffici.pdf' },
            { name: 'Piano_Sicurezza.pdf' },
        ],
    },
    chatHistory: {
        company: [
            { role: 'assistant', text: 'Benvenuto! Chat generale dell\'azienda.', ts: Date.now() },
        ],
    },
    analyticsReports: [
        {
            created_at: '2025-01-15T10:30:00',
            period_days: 7,
            report: 'Report qualità ultimi 7 giorni:\n\n✅ Accuratezza: 95%\n⚡ Tempo medio risposta: 2.3s',
            metrics: {
                total_chats: 145,
                avg_response_time: 2.3,
                accuracy: 0.95,
            },
            bad_examples: [],
        },
    ],
};

export async function mockFetch(url, options = {}) {
    if (!USE_MOCK_DATA) {
        return fetch(url, options);
    }

    console.log('[MOCK API]', options.method || 'GET', url);

    await delay(MOCK_DELAY);

    // ============ PROJECTS ============

    if ((url.includes('/api/projects/list') || url === '/api/projects') && !options.method) {
        return {
            ok: true,
            json: async () => ({ items: mockStorage.projects }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    const projectIdMatch = url.match(/\/api\/projects\/([^/]+)$/);
    if (projectIdMatch && !options.method) {
        const id = projectIdMatch[1];
        const project = mockStorage.projects.find(p => p.id === id);

        if (project) {
            return {
                ok: true,
                json: async () => project,
                headers: new Headers({ 'content-type': 'application/json' }),
            };
        }
    }

    if (url.includes('/api/projects') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        const newProject = {
            id: `mock-${Date.now()}`,
            ...body,
            works: [],
            meta_extra: {},
        };
        mockStorage.projects.push(newProject);

        return {
            ok: true,
            json: async () => ({ project: newProject }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (projectIdMatch && options.method === 'PATCH') {
        const id = projectIdMatch[1];
        const body = JSON.parse(options.body);

        const projectIdx = mockStorage.projects.findIndex(p => p.id === id);
        if (projectIdx >= 0) {
            // Deep merge per meta_extra
            mockStorage.projects[projectIdx] = {
                ...mockStorage.projects[projectIdx],
                ...body,
                meta_extra: {
                    ...mockStorage.projects[projectIdx].meta_extra,
                    ...body.meta_extra,
                },
            };

            return {
                ok: true,
                json: async () => mockStorage.projects[projectIdx],
                headers: new Headers({ 'content-type': 'application/json' }),
            };
        }
    }

    if (projectIdMatch && options.method === 'DELETE') {
        const id = projectIdMatch[1];
        mockStorage.projects = mockStorage.projects.filter(p => p.id !== id);

        return {
            ok: true,
            json: async () => ({ success: true }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/status') && options.method === 'POST') {
        const id = url.match(/\/api\/projects\/([^/]+)\/status/)[1];
        const projectIdx = mockStorage.projects.findIndex(p => p.id === id);

        if (projectIdx >= 0) {
            const currentStatus = mockStorage.projects[projectIdx].status;
            const newStatus = currentStatus === 'Confermato' ? 'Preventivo' : 'Confermato';
            mockStorage.projects[projectIdx].status = newStatus;

            return {
                ok: true,
                json: async () => ({
                    success: true,
                    workers_total: mockStorage.workers.length,
                    projects_total: mockStorage.projects.length,
                    active_projects: mockStorage.projects.filter(p => p.status === 'Confermato').length,
                }),
                headers: new Headers({ 'content-type': 'application/json' }),
            };
        }
    }

    // ============ WORKS MANAGEMENT ============

    if (url.includes('/works/assign') && options.method === 'POST') {
        const id = url.match(/\/api\/projects\/([^/]+)\/works/)[1];
        const body = JSON.parse(options.body);

        const project = mockStorage.projects.find(p => p.id === id);
        if (project) {
            const work = project.works?.find(w => w.work_name === body.work_name);

            if (work) {
                if (!work.workers) work.workers = [];

                const worker = mockStorage.workers.find(w => w.id === body.worker_id);
                if (worker) {
                    work.workers.push({
                        worker_id: body.worker_id,
                        name: worker.name,
                        role: worker.role,
                        start_date: body.start_date,
                        end_date: body.end_date,
                    });
                }
            }

            return {
                ok: true,
                json: async () => ({ success: true }),
                headers: new Headers({ 'content-type': 'application/json' }),
            };
        }
    }

    if (url.includes('/works/unassign') && options.method === 'POST') {
        const id = url.match(/\/api\/projects\/([^/]+)\/works/)[1];
        const body = JSON.parse(options.body);

        const project = mockStorage.projects.find(p => p.id === id);
        if (project) {
            const work = project.works?.find(w => w.work_name === body.work_name);

            if (work && work.workers) {
                work.workers = work.workers.filter(w => w.worker_id !== body.worker_id);
            }

            return {
                ok: true,
                json: async () => ({ success: true }),
                headers: new Headers({ 'content-type': 'application/json' }),
            };
        }
    }

    if (url.includes('/works/status') && options.method === 'PATCH') {
        const id = url.match(/\/api\/projects\/([^/]+)\/works/)[1];
        const body = JSON.parse(options.body);

        const project = mockStorage.projects.find(p => p.id === id);
        if (project) {
            const work = project.works?.find(w => w.work_name === body.work_name);

            if (work) {
                work.status = body.status;
                if (body.status === 'in_progress' && !work.start_date_actual) {
                    work.start_date_actual = new Date().toISOString().split('T')[0];
                }
                if (body.status === 'completed' && !work.end_date_actual) {
                    work.end_date_actual = new Date().toISOString().split('T')[0];
                }
            }

            return {
                ok: true,
                json: async () => ({ success: true }),
                headers: new Headers({ 'content-type': 'application/json' }),
            };
        }
    }

    // ============ DOCUMENTS ============

    if (url.includes('/api/company/documents') && !options.method) {
        return {
            ok: true,
            json: async () => ({ documents: mockStorage.companyDocuments }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/api/company/documents') && options.method === 'POST') {
        mockStorage.companyDocuments.push({ name: 'Documento_Caricato.pdf' });
        return {
            ok: true,
            json: async () => ({ success: true }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    const projectDocsMatch = url.match(/\/api\/projects\/([^/]+)\/documents$/);
    if (projectDocsMatch && !options.method) {
        const id = projectDocsMatch[1];
        return {
            ok: true,
            json: async () => ({
                documents: mockStorage.projectDocuments[id] || []
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (projectDocsMatch && options.method === 'POST') {
        const id = projectDocsMatch[1];
        if (!mockStorage.projectDocuments[id]) {
            mockStorage.projectDocuments[id] = [];
        }
        mockStorage.projectDocuments[id].push({ name: 'Documento_Caricato.pdf' });

        return {
            ok: true,
            json: async () => ({ success: true }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    // ============ CHAT ============

    if (url.includes('/api/chat') && !url.includes('/project/') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        await delay(500);

        return {
            ok: true,
            json: async () => ({
                reply: `Risposta mock a: "${body.message}"`,
                sources: [{ title: 'Fonte Mock', snippet: 'Info mock' }],
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    const projectChatMatch = url.match(/\/api\/chat\/project\/([^/]+)$/);
    if (projectChatMatch && options.method === 'POST') {
        const body = JSON.parse(options.body);
        await delay(500);

        return {
            ok: true,
            json: async () => ({
                text: `Risposta mock per cantiere: "${body.message}"`,
                sources: [{ title: 'Doc Cantiere', snippet: 'Info progetto' }],
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    // ============ WORKERS ============

    if (url.includes('/api/workers') && !options.method) {
        return {
            ok: true,
            json: async () => mockStorage.workers,
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/api/workers') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        const newWorker = {
            id: `W-${1000 + mockStorage.workers.length + 1}`,
            ...body,
        };
        mockStorage.workers.push(newWorker);

        return {
            ok: true,
            json: async () => newWorker,
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    const workerIdMatch = url.match(/\/api\/workers\/([^/]+)$/);
    if (workerIdMatch && options.method === 'DELETE') {
        const id = workerIdMatch[1];
        mockStorage.workers = mockStorage.workers.filter(w => w.id !== id);

        return {
            ok: true,
            json: async () => ({ success: true }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    // ============ COMPANY / DASHBOARD ============

    if (url.includes('/api/company/overview') || url.includes('/api/dashboard/summary')) {
        return {
            ok: true,
            json: async () => ({
                workers_total: mockStorage.workers.length,
                projects_total: mockStorage.projects.length,
                active_projects: mockStorage.projects.filter(p => p.status === 'Confermato').length,
                active_workers: mockStorage.workers.filter(w => w.is_active).length,
                documents_total: mockStorage.companyDocuments.length,
                operai: mockStorage.workers.length,
                cantieri: mockStorage.projects.length,
                cantieri_attivi: mockStorage.projects.filter(p => p.status === 'Confermato').length,
                operai_attivi: mockStorage.workers.filter(w => w.is_active).length,
                documenti_azienda: mockStorage.companyDocuments.length,
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    // ============ ANALYTICS ============

    if (url.includes('/analytics/summary')) {
        return {
            ok: true,
            json: async () => ({
                total_chats: 245,
                last_days_chats: 68,
                error_rate: 0.05,
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/analytics/reports') && !url.includes('latest')) {
        return {
            ok: true,
            json: async () => mockStorage.analyticsReports,
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/analytics/reports/latest')) {
        return {
            ok: true,
            json: async () => ({
                ok: true,
                report: mockStorage.analyticsReports[0],
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/analytics/reports/generate') && options.method === 'POST') {
        await delay(1500);
        return {
            ok: true,
            json: async () => ({ success: true }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    // ============ COMPUTO OPERATIONS ============

    if (url.includes('/computo/upload') && options.method === 'POST') {
        return {
            ok: true,
            json: async () => ({ success: true, message: 'Computo caricato' }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/computo/generate') && options.method === 'POST') {
        await delay(2000);
        return {
            ok: true,
            json: async () => ({ success: true, pdf_report_url: '/mock-pdf-url' }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/lavori/generate') && options.method === 'POST') {
        await delay(1500);
        return {
            ok: true,
            json: async () => ({
                success: true,
                works: [
                    { name: 'Demolizione', duration_days: 2 },
                    { name: 'Impianti', duration_days: 5 },
                ],
            }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/plan') && options.method === 'POST') {
        await delay(1000);
        return {
            ok: true,
            json: async () => ({ success: true }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    if (url.includes('/schedule/assign') && options.method === 'POST') {
        await delay(1000);
        return {
            ok: true,
            json: async () => ({ success: true, assigned: 5, deficits: [] }),
            headers: new Headers({ 'content-type': 'application/json' }),
        };
    }

    // Fallback
    console.warn('[MOCK API] Unhandled endpoint:', url);
    return {
        ok: false,
        status: 404,
        json: async () => ({ error: 'Mock endpoint not implemented' }),
        headers: new Headers({ 'content-type': 'application/json' }),
    };
}

export { USE_MOCK_DATA, MOCK_DELAY };