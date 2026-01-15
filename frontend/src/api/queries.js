import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAPI, postAPI, deleteAPI, patchAPI } from './client';

// ============ COMPANY / DASHBOARD ============

export function useCompanyOverview() {
    return useQuery({
        queryKey: ['company', 'overview'],
        queryFn: () => getAPI('/api/company/overview'),
    });
}

export function useDashboardSummary() {
    return useQuery({
        queryKey: ['dashboard', 'summary'],
        queryFn: () => getAPI('/api/company/dashboard/summary'),
    });
}

// ============ PROJECTS ============

export function useProjects() {
    return useQuery({
        queryKey: ['projects'],
        queryFn: () => getAPI('/api/projects/list'),
        select: (data) => data.items || [],
    });
}

export function useProject(projectId) {
    return useQuery({
        queryKey: ['projects', projectId],
        queryFn: () => getAPI(`/api/projects/${projectId}`),
        enabled: !!projectId,
        select: (data) => data.project || data,
    });
}

export function useCreateProject() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (data) => postAPI('/api/projects', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            queryClient.invalidateQueries({ queryKey: ['dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['company'] });
        },
    });
}

export function useDeleteProject() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (projectId) => deleteAPI(`/api/projects/${projectId}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            queryClient.invalidateQueries({ queryKey: ['dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['company'] });
        },
    });
}

// ============ WORKERS ============

export function useWorkers(params = {}) {
    return useQuery({
        queryKey: ['workers', params],
        queryFn: () => {
            // Ensure we fetch enough workers so UI can resolve worker names by id
            // (otherwise WorkCard falls back to `Worker xxxx` for workers not in the first page)
            const searchParams = new URLSearchParams(params);
            if (!searchParams.get('page')) searchParams.set('page', '1');
            if (!searchParams.get('per_page')) searchParams.set('per_page', '500');
            return getAPI(`/api/workers?${searchParams}`);
        },
        select: (data) => data.items || data || [],  // ✅ Estrae items dall'API
    });
}

export function useCreateWorker() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (data) => postAPI('/api/workers', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['workers'] });
            queryClient.invalidateQueries({ queryKey: ['dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['company'] });
        },
    });
}

export function useDeleteWorker() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (workerId) => deleteAPI(`/api/workers/${workerId}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['workers'] });
            queryClient.invalidateQueries({ queryKey: ['dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['company'] });
        },
    });
}

// ============ DOCUMENTS ============

export function useCompanyDocuments() {
    return useQuery({
        queryKey: ['company', 'documents'],
        queryFn: () => getAPI('/api/company/documents'),
    });
}

export function useUploadCompanyDocument() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (file) => {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch('/api/company/documents', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Upload failed');
            }

            return response.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['company', 'documents'] });
            queryClient.invalidateQueries({ queryKey: ['company', 'overview'] });
        },
    });
}

// ============ PROJECT STATUS ============

export function useToggleProjectStatus() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (projectId) => postAPI(`/api/projects/${projectId}/status`, {}),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            queryClient.invalidateQueries({ queryKey: ['dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['company'] });
        },
    });
}

// ============ PROJECT DOCUMENTS ============

export function useProjectDocuments(projectId) {
    return useQuery({
        queryKey: ['projects', projectId, 'documents'],
        queryFn: () => getAPI(`/api/projects/${projectId}/documents`),
        enabled: !!projectId,
    });
}

export function useUploadProjectDocument() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, file }) => {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch(`/api/projects/${projectId}/documents`, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Upload failed');
            }

            return response.json();
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({
                queryKey: ['projects', variables.projectId, 'documents']
            });
        },
    });
}

// ============ PROJECT CHAT ============

export function useSendProjectMessage() {
    return useMutation({
        mutationFn: async ({ projectId, message }) => {
            const response = await fetch(`/api/chat/project/${projectId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Chat error');
            }

            return {
                text: data.reply || data.answer || data.text || '',
                sources: data.sources || data.web_sources || data.local_sources || [],
            };
        },
    });
}

// ============ ANALYTICS ============

export function useAnalyticsSummary(days = 7) {
    return useQuery({
        queryKey: ['analytics', 'summary', days],
        queryFn: () => getAPI(`/analytics/summary?days=${days}`),
    });
}

export function useAnalyticsReports(limit = 5) {
    return useQuery({
        queryKey: ['analytics', 'reports', limit],
        queryFn: () => getAPI(`/analytics/reports?limit=${limit}`),
    });
}

export function useAnalyticsLatestReport() {
    return useQuery({
        queryKey: ['analytics', 'latest'],
        queryFn: () => getAPI('/analytics/reports/latest'),
    });
}

export function useGenerateAnalyticsReport() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (params = {}) =>
            postAPI('/analytics/reports/generate', {
                days: params.days || 7,
                limit: params.limit || 500,
                site_id: params.site_id || null,
            }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['analytics'] });
        },
    });
}

// ============ COMPUTO METRICO ============

export function useUploadComputo() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, file }) => {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch(`/api/projects/${projectId}/computo/upload`, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Upload failed');
            }

            return response.json();
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}

export function useGenerateComputo() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, description }) => {
            return postAPI(`/api/projects/${projectId}/computo/generate`, { description });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}


// ============ UPDATE COMPUTO ============

export function useUpdateComputo() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, computo }) => {
            // Usa PATCH per aggiornare meta_extra.computo_metrico
            return patchAPI(`/api/projects/${projectId}`, {
                meta_extra: {
                    computo_metrico: computo
                }
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}

export function useGenerateLavori() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, startDate }) => {
            return postAPI(`/api/projects/${projectId}/lavori/generate`, {
                start_date: startDate
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}

// ============ PLANNING & SCHEDULING ============

export function usePlanProject() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, startFrom = 'auto', replace = true }) => {
            return postAPI(`/api/projects/${projectId}/plan`, {
                start_from: startFrom,
                replace: replace
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}

export function useAssignWorkers() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (projectId) => {
            return postAPI(`/api/projects/${projectId}/schedule/assign`, {});
        },
        onSuccess: (_, projectId) => {
            queryClient.invalidateQueries({ queryKey: ['projects', projectId] });
        },
    });
}

// ============ UPDATE PROJECT ============

export function useUpdateProject() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, data }) => {
            return patchAPI(`/api/projects/${projectId}`, data);
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
            queryClient.invalidateQueries({ queryKey: ['projects'] });
        },
    });
}

// ============ PDF GENERATION FROM JSON ============

export function useGenerateComputoPDF() {
    return useMutation({
        mutationFn: async (projectId) => {
            const response = await fetch(`/api/projects/${projectId}/computo/pdf`, {
                method: 'POST',
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'PDF generation failed');
            }

            // Return blob for download
            const blob = await response.blob();
            return blob;
        },
    });
}

// ============ WORK ASSIGNMENTS ============

export function useAssignWorkerToWork() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, workName, workerId, startDate, endDate }) => {
            return postAPI(`/api/projects/${projectId}/works/assign`, {
                work_name: workName,
                worker_id: workerId,
                start_date: startDate,
                end_date: endDate,
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}

export function useRemoveWorkerFromWork() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, workName, workerId }) => {
            return postAPI(`/api/projects/${projectId}/works/unassign`, {
                work_name: workName,
                worker_id: workerId,
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}

export function useUpdateWorkStatus() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ projectId, workName, status }) => {
            return patchAPI(`/api/projects/${projectId}/works/status`, {
                work_name: workName,
                status: status,
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId] });
        },
    });
}