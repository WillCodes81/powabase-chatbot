import { Navigate, Route, Routes } from 'react-router-dom';
import { SignInPage } from './auth/SignInPage';
import { SignUpPage } from './auth/SignUpPage';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { AppShell } from './components/AppShell';
import { DashboardPage } from './pages/DashboardPage';
import { CreateAgentPage } from './pages/CreateAgentPage';
import { CreateChatbotPage } from './pages/CreateChatbotPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { ChatbotDetailPage } from './pages/ChatbotDetailPage';

export function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignInPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agents/new" element={<CreateAgentPage />} />
        <Route path="/agents/:agentId" element={<AgentDetailPage />} />
        <Route path="/chatbots/new" element={<CreateChatbotPage />} />
        <Route path="/chatbots/:chatbotId" element={<ChatbotDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
