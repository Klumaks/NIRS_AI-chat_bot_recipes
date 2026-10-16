import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router";
import { queryClient } from "./lib/query";
import { AuthProvider, Protected, useAuth } from "./auth/Auth";
import { AppShell } from "./components/AppShell";
import { AuthPage } from "./pages/AuthPage";
import { RagPage } from "./pages/RagPage";
import { ChatPage } from "./pages/ChatPage";
import { UsersPage, ActivityPage, DiagnosticPage } from "./pages/AdminPages";
import { Brand } from "./components/Brand";
import { Loading } from "./components/UI";
function Home() {
  const a = useAuth();
  return a.loading ? (
    <Loading />
  ) : (
    <Navigate to={a.user ? "/chat" : "/login"} replace />
  );
}
function StatusPage({ forbidden = false }: { forbidden?: boolean }) {
  return (
    <main className="status-page">
      <Brand />
      <p className="status-number">{forbidden ? "403" : "404"}</p>
      <h1>
        {forbidden ? "Здесь нужны права администратора" : "Такой страницы нет"}
      </h1>
      <p className="muted">
        {forbidden
          ? "Вам по-прежнему доступны ваши чаты и рецепты."
          : "Возможно, адрес изменился. Вернёмся на кухню?"}
      </p>
      <Link to="/chat" className="button primary">
        На кухню
      </Link>
    </main>
  );
}
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<AuthPage key="login" />} />
            <Route
              path="/register"
              element={<AuthPage key="register" register />}
            />
            <Route
              element={
                <Protected>
                  <AppShell />
                </Protected>
              }
            >
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/chat/:chatId" element={<ChatPage />} />
              <Route
                path="/chat/:chatId/recipe/:recipeId"
                element={<ChatPage />}
              />
              <Route
                path="/admin"
                element={
                  <Protected admin>
                    <Navigate to="/admin/users" replace />
                  </Protected>
                }
              />
              <Route
                path="/admin/users"
                element={
                  <Protected admin>
                    <UsersPage />
                  </Protected>
                }
              />
              <Route path="/admin/rag" element={<Protected admin><RagPage /></Protected>} />
              <Route
                path="/admin/activity"
                element={
                  <Protected admin>
                    <ActivityPage />
                  </Protected>
                }
              />
              <Route
                path="/admin/requests/:requestId"
                element={
                  <Protected admin>
                    <DiagnosticPage />
                  </Protected>
                }
              />
            </Route>
            <Route path="/403" element={<StatusPage forbidden />} />
            <Route path="*" element={<StatusPage />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
