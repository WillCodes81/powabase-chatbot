import { Navigate, Route, Routes } from 'react-router-dom';
import { SignInPage } from './auth/SignInPage';
import { SignUpPage } from './auth/SignUpPage';
import { ProtectedRoute } from './auth/ProtectedRoute';
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
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/agents/new" element={<ProtectedRoute><CreateAgentPage /></ProtectedRoute>} />
      <Route path="/agents/:agentId" element={<ProtectedRoute><AgentDetailPage /></ProtectedRoute>} />
      <Route path="/chatbots/new" element={<ProtectedRoute><CreateChatbotPage /></ProtectedRoute>} />
      <Route path="/chatbots/:chatbotId" element={<ProtectedRoute><ChatbotDetailPage /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
