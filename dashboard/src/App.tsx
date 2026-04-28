import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WebSocketProvider } from './context/WebSocketContext';
import { Dashboard } from './pages/Dashboard';
import { Soignant } from './pages/Soignant';
import { ResidentDetail } from './pages/ResidentDetail';
import { MobileResident } from './pages/MobileResident';
import { Famille } from './pages/Famille';
import { AdminFamille } from './pages/AdminFamille';
import { AlbumActivites } from './pages/AlbumActivites';
import { SimulateurConfig } from './pages/SimulateurConfig';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/soignant" element={<Soignant />} />
            <Route path="/soignant/:id" element={<Soignant />} />
            <Route path="/resident/:id" element={<ResidentDetail />} />
            <Route path="/mobile/resident/:id" element={<MobileResident />} />
            <Route path="/famille" element={<Famille />} />
            <Route path="/admin-famille" element={<AdminFamille />} />
            <Route path="/album-activites" element={<AlbumActivites />} />
            <Route path="/simulateur/config" element={<SimulateurConfig />} />
          </Routes>
        </BrowserRouter>
      </WebSocketProvider>
    </QueryClientProvider>
  );
}
