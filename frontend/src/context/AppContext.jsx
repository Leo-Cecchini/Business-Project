import { createContext, useContext, useState, useEffect } from 'react';

const AppContext = createContext();

export function AppProvider({ children }) {
    const [selectedProjectId, setSelectedProjectId] = useState('');
    const [selectedProjectName, setSelectedProjectName] = useState('');
    const [recentProjectIds, setRecentProjectIds] = useState([]);

    // Carica progetti recenti dal localStorage
    useEffect(() => {
        try {
            const stored = localStorage.getItem('recent_projects');
            if (stored) {
                setRecentProjectIds(JSON.parse(stored));
            }
        } catch (error) {
            console.error('Error loading recent projects:', error);
        }
    }, []);

    // Salva progetti recenti nel localStorage
    useEffect(() => {
        try {
            localStorage.setItem('recent_projects', JSON.stringify(recentProjectIds));
        } catch (error) {
            console.error('Error saving recent projects:', error);
        }
    }, [recentProjectIds]);

    // Funzione per selezionare un progetto
    const selectProject = (projectId, projectName = '') => {
        setSelectedProjectId(projectId);
        setSelectedProjectName(projectName);

        // Aggiungi ai recenti (massimo 5)
        if (projectId) {
            setRecentProjectIds(prev => {
                const filtered = prev.filter(id => id !== projectId);
                return [projectId, ...filtered].slice(0, 5);
            });
        }
    };

    // Funzione per deselezionare
    const clearProject = () => {
        setSelectedProjectId('');
        setSelectedProjectName('');
    };

    const value = {
        selectedProjectId,
        selectedProjectName,
        recentProjectIds,
        selectProject,
        clearProject,
    };

    return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
    const context = useContext(AppContext);
    if (!context) {
        throw new Error('useApp must be used within AppProvider');
    }
    return context;
}