import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { AppProvider } from './context/AppContext';
import Layout from './components/layout/Layout';
import Azienda from './pages/Azienda';
import Cantieri from './pages/Cantieri';
import CantieriOverview from './pages/CantieriOverview';
import CantieriComputo from './pages/CantieriComputo';
import CantieriLavori from './pages/CantieriLavori';
import Analytics from './pages/Analytics';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Layout />}>
              <Route index element={<Navigate to="/azienda" replace />} />
              <Route path="azienda" element={<Azienda />} />
              <Route path="cantieri" element={<Cantieri />}>
                <Route index element={<CantieriOverview />} />
                <Route path="computo" element={<CantieriComputo />} />
                <Route path="lavori" element={<CantieriLavori />} />
              </Route>
              <Route path="analytics" element={<Analytics />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AppProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

export default App;