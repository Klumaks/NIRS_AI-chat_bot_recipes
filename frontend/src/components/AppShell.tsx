import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Plus,
  LogOut,
  Menu,
  Trash2,
  MessageSquare,
  Users,
  Activity,
  Database,
  X,
} from "lucide-react";
import { Brand, Sage } from "./Brand";
import { Modal, ErrorBox } from "./UI";
import { useAuth } from "../auth/Auth";
import { authApi, chatApi } from "../api/services";
import { queryClient } from "../lib/query";
import type { ChatSummary } from "../api/types";
import { useLastChat, forgetChat } from "../lib/lastChat";
export function AppShell() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const [logoutError, setLogoutError] = useState<unknown>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const history = useQuery({
    queryKey: ["chats", user!.user_id],
    queryFn: ({ signal }) => chatApi.list(signal),
  });
  const lastChat = useLastChat(user!.user_id);
  const resumePath = lastChat || (history.data?.items[0] ? "/chat/" + encodeURIComponent(history.data.items[0].chat_id) : "/chat");
  const remove = useMutation({
    mutationFn: (id: string) => chatApi.remove(id),
    onSuccess: async (_d, id) => {
      forgetChat(user!.user_id, id);
      await queryClient.cancelQueries({
        queryKey: ["chat", user!.user_id, id],
      });
      queryClient.removeQueries({ queryKey: ["chat", user!.user_id, id] });
      await queryClient.invalidateQueries({
        queryKey: ["chats", user!.user_id],
      });
      setDeleting(null);
      if (location.pathname.startsWith("/chat/" + id)) void navigate("/chat");
    },
  });
  async function logout() {
    try {
      await authApi.logout();
      await queryClient.cancelQueries();
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.setQueryData(["auth"], null);
      void navigate("/login", { replace: true });
    } catch (e) {
      setLogoutError(e);
    }
  }
  const close = () => setOpen(false);
  return (
    <div className="app">
      <header className="app-header">
        <button
          className="icon-button mobile-menu"
          onClick={() => setOpen(true)}
          aria-label="Открыть историю"
        >
          <Menu />
        </button>
        <Link to="/chat" onClick={close}>
          <Brand />
        </Link>
        <span className="header-note">Вдохновение для вашей кухни</span>
        <span className="account-email">{user!.email}</span>
        <button className="text-button" onClick={() => void logout()}>
          <LogOut size={17} />
          <span>Выйти</span>
        </button>
      </header>
      {open && (
        <button
          className="sidebar-backdrop"
          aria-label="Закрыть историю"
          onClick={close}
        />
      )}
      <aside className={"sidebar " + (open ? "is-open" : "")}>
        <div className="sidebar-heading">
          <span>ВАША КУХНЯ</span>
          <button
            className="icon-button mobile-menu"
            aria-label="Закрыть историю"
            onClick={close}
          >
            <X size={18} />
          </button>
        </div>
        <Link to="/chat" className="button primary full" onClick={close}>
          <Plus size={18} />
          Новый подбор
        </Link>
        <nav aria-label="Основная навигация">
          <NavLink
            to={resumePath}
            end={resumePath === "/chat"}
            aria-disabled={!lastChat && !history.isSuccess}
            onClick={(event) => {
              if (!lastChat && !history.isSuccess) { event.preventDefault(); return; }
              close();
            }}
          >
            <MessageSquare size={17} />
            Чат с ИИ-шефом
          </NavLink>
          {user!.role === "admin" && (
            <>
              <NavLink to="/admin/users" onClick={close}>
                <Users size={17} />
                Пользователи
              </NavLink>
              <NavLink to="/admin/rag" onClick={close}><Database size={17} />Данные RAG</NavLink>
              <NavLink to="/admin/activity" onClick={close}>
                <Activity size={17} />
                Активность
              </NavLink>
            </>
          )}
        </nav>
        <div className="history-heading">История чатов</div>
        {history.isPending ? (
          <small>Загружаем историю…</small>
        ) : history.error ? (
          <ErrorBox
            error={history.error}
            onRetry={() => void history.refetch()}
          />
        ) : (
          <ul className="history-list">
            {history.data?.items.map((c) => (
              <li key={c.chat_id}>
                <NavLink
                  to={"/chat/" + c.chat_id}
                  onClick={close}
                  title={c.title}
                >
                  {c.title}
                </NavLink>
                <button
                  className="icon-button delete-chat"
                  aria-label={"Удалить чат " + c.title}
                  onClick={() => {
                    remove.reset();
                    setDeleting(c);
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
            {!history.data?.items.length && (
              <li className="muted">Здесь появится ваш первый подбор.</li>
            )}
          </ul>
        )}
        <div className="sidebar-footer">
          <Sage />
          <p>
            От продуктов —<br />к любимому блюду.
          </p>
          <small>
            Вернитесь к рецепту
            <br />в любой момент.
          </small>
        </div>
      </aside>
      <main className="workspace">
        {!!logoutError && <ErrorBox error={logoutError} />}
        <Outlet />
      </main>
      {deleting && (
        <Modal title="Удалить чат?" onClose={() => setDeleting(null)}>
          <p>Переписку «{deleting.title}» восстановить не получится.</p>
          {remove.error && <ErrorBox error={remove.error} />}
          <div className="dialog-actions">
            <button
              className="button secondary"
              onClick={() => setDeleting(null)}
              disabled={remove.isPending}
            >
              Отмена
            </button>
            <button
              className="button danger"
              onClick={() => remove.mutate(deleting.chat_id)}
              disabled={remove.isPending}
            >
              Удалить
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
