import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { Layout } from "./Layout";
import { AuthProvider, useAuth } from "./lib/auth";
import { CallPage } from "./pages/Call/CallPage";
import { DemoAdminPage } from "./pages/DemoAdminPage";
import { MetricsPage } from "./pages/MetricsPage";
import { Member360Page } from "./pages/Member360Page";
import { LoginPage, MembersPage, TasksPage } from "./pages/OtherPages";
import { OldWayPage } from "./pages/OldWayPage";
import { QueuePage } from "./pages/QueuePage";

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <p className="p-4">Signing in…</p>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/demo/old-way" element={<OldWayPage />} />
      <Route element={<Protected />}>
        <Route path="/queue" element={<QueuePage />} />
        <Route path="/members" element={<MembersPage />} />
        <Route path="/members/:id" element={<Member360Page />} />
        <Route path="/members/:id/call" element={<CallPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/demo-admin" element={<DemoAdminPage />} />
        <Route path="/admin/metrics" element={<MetricsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/queue" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}
