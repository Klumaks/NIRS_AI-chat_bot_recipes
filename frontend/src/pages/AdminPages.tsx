import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Plus,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  MinusCircle,
  AlertCircle,
} from "lucide-react";
import { adminApi } from "../api/services";
import type { Role } from "../api/types";
import { queryClient } from "../lib/query";
import { userSchema } from "../lib/forms";
import { Loading, ErrorBox, Modal, PageTitle, Empty } from "../components/UI";
import { useAuth } from "../auth/Auth";
const date = (s: string) => new Date(s).toLocaleString("ru-RU");
const eventNames: Record<string, string> = {
  search: "Подбор блюд",
  filter: "Фильтрация",
  select_recipe: "Выбор рецепта",
  question: "Вопрос по рецепту",
  login: "Вход",
  logout: "Выход",
  register: "Регистрация",
  create_user: "Создание аккаунта",
  delete_chat: "Удаление чата",
};
export function UsersPage() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const q = useQuery({
    queryKey: ["admin-users", user!.user_id],
    queryFn: ({ signal }) => adminApi.users(signal),
  });
  const form = useForm<{ email: string; password: string; role: Role }>({
    resolver: zodResolver(userSchema),
    defaultValues: { email: "", password: "", role: "user" },
  });
  const create = useMutation({
    mutationFn: (v: { email: string; password: string; role: Role }) =>
      adminApi.create(v.email, v.password, v.role),
    onSuccess: async (u) => {
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setOpen(false);
      form.reset();
      setNotice("Аккаунт " + u.email + " создан");
    },
  });
  return (
    <section>
      <PageTitle title="Пользователи">
        Создавайте аккаунты и назначайте роль при создании.
      </PageTitle>
      <div className="section-toolbar">
        <span className="muted">{q.data?.total ?? 0} аккаунтов</span>
        <button
          className="button primary"
          onClick={() => {
            create.reset();
            setNotice("");
            setOpen(true);
          }}
        >
          <Plus size={17} />
          Создать аккаунт
        </button>
      </div>
      {notice && (
        <p className="success-notice" role="status">
          {notice}
        </p>
      )}
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Роль</th>
                <th>Создан</th>
              </tr>
            </thead>
            <tbody>
              {q.data?.items.map((u) => (
                <tr key={u.user_id}>
                  <td>
                    {u.email}
                    {u.user_id === user!.user_id && (
                      <span className="you">Вы</span>
                    )}
                  </td>
                  <td>
                    <span className={"role-badge " + u.role}>
                      {u.role === "admin" ? "Администратор" : "Пользователь"}
                    </span>
                  </td>
                  <td>{u.created_at ? date(u.created_at) : "нет данных"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && (
        <Modal title="Новый аккаунт" onClose={() => setOpen(false)}>
          <p className="muted">
            Администратор может создать пользователя или другого администратора.
          </p>
          <form
            onSubmit={form.handleSubmit((v) => create.mutate(v))}
            noValidate
          >
            <label>
              Email
              <input
                type="email"
                autoComplete="off"
                {...form.register("email")}
                autoFocus
              />
              <span className="field-error">
                {form.formState.errors.email?.message}
              </span>
            </label>
            <label>
              Начальный пароль
              <input
                type="password"
                autoComplete="new-password"
                {...form.register("password")}
              />
              <span className="field-error">
                {form.formState.errors.password?.message}
              </span>
            </label>
            <fieldset className="role-picker">
              <legend>Роль</legend>
              <label className="role-option">
                <input type="radio" value="user" aria-label="Пользователь" {...form.register("role")} />
                <span><strong>Пользователь</strong><small>Свои чаты, подборы и рецепты</small></span>
              </label>
              <label className="role-option">
                <input type="radio" value="admin" aria-label="Администратор" {...form.register("role")} />
                <span><strong>Администратор</strong><small>Все возможности пользователя и управление аккаунтами</small></span>
              </label>
            </fieldset>
            {create.error && <ErrorBox error={create.error} />}
            <div className="dialog-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => setOpen(false)}
                disabled={create.isPending}
              >
                Отмена
              </button>
              <button className="button primary" disabled={create.isPending}>
                Создать
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
export function ActivityPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState({ from: "", to: "", user_id: "" });
  const [draft, setDraft] = useState(filters);
  const [offset, setOffset] = useState(0);
  const p = new URLSearchParams({ limit: "20", offset: String(offset) });
  for (const [k, v] of Object.entries(filters)) if (v) p.set(k, v);
  const q = useQuery({
    queryKey: ["activity", user!.user_id, p.toString()],
    queryFn: ({ signal }) => adminApi.activity(p, signal),
  });
  const users = useQuery({
    queryKey: ["admin-users", user!.user_id],
    queryFn: ({ signal }) => adminApi.users(signal),
  });
  return (
    <section>
      <PageTitle title="Активность">
        События использования и путь запроса. Тексты переписки здесь не
        сохраняются.
      </PageTitle>
      <form
        className="activity-filters"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setFilters(draft);
        }}
      >
        <label>
          С даты
          <input
            type="date"
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          />
        </label>
        <label>
          По дату
          <input
            type="date"
            value={draft.to}
            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          />
        </label>
        <label>
          Пользователь
          <select
            value={draft.user_id}
            onChange={(e) => setDraft({ ...draft, user_id: e.target.value })}
          >
            <option value="">Все пользователи</option>
            {users.data?.items.map((u) => (
              <option value={u.user_id} key={u.user_id}>
                {u.email}
              </option>
            ))}
          </select>
        </label>
        <button className="button secondary">Применить</button>
        <button
          type="button"
          className="text-button"
          onClick={() => {
            setDraft({ from: "", to: "", user_id: "" });
            setFilters({ from: "", to: "", user_id: "" });
            setOffset(0);
          }}
        >
          Сбросить
        </button>
      </form>
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} onRetry={() => void q.refetch()} />
      ) : !q.data?.items.length ? (
        <Empty title="За этот период событий нет">
          Попробуйте другой период или выполните действие в чате.
        </Empty>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Пользователь</th>
                  <th>Событие</th>
                  <th>Статус</th>
                  <th>Запрос</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((e) => (
                  <tr key={e.request_id}>
                    <td className="nowrap">{date(e.occurred_at)}</td>
                    <td>
                      {users.data?.items.find((u) => u.user_id === e.user_id)
                        ?.email ||
                        e.user_id ||
                        "Гость"}
                    </td>
                    <td>{eventNames[e.event_type] || e.event_type}</td>
                    <td>
                      <span className={"status " + e.status}>
                        {e.status === "ok" ? "Успешно" : "Ошибка"}
                      </span>
                    </td>
                    <td>
                      <Link
                        className="text-button"
                        to={"/admin/requests/" + e.request_id}
                      >
                        Диагностика <ArrowRight size={15} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span className="muted">
              {offset + 1}–{offset + q.data.items.length} из {q.data.total}
            </span>
            <button
              className="button secondary"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Назад
            </button>
            <button
              className="button secondary"
              disabled={offset + 20 >= q.data.total}
              onClick={() => setOffset(offset + 20)}
            >
              Далее
            </button>
          </div>
        </>
      )}
    </section>
  );
}
export function DiagnosticPage() {
  const { requestId } = useParams();
  const { user } = useAuth();
  const q = useQuery({
    queryKey: ["diagnostic", user!.user_id, requestId],
    queryFn: ({ signal }) => adminApi.diagnostic(requestId!, signal),
  });
  return (
    <section>
      <Link className="text-button back-link" to="/admin/activity">
        <ArrowLeft size={17} />К активности
      </Link>
      <PageTitle title="Диагностика запроса">
        Какие этапы действительно выполнялись.
      </PageTitle>
      {q.isPending ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        q.data && (
          <>
            <code className="request-id">{q.data.request_id}</code>
            <dl className="diagnostic-summary">
              <div>
                <dt>Корпус</dt>
                <dd>{q.data.corpus_version || "не использовался"}</dd>
              </div>
              <div>
                <dt>Индекс</dt>
                <dd>{q.data.index_version || "не использовался"}</dd>
              </div>
              <div>
                <dt>Нормализация</dt>
                <dd>{q.data.normalization_mode || "не выполнялась"}</dd>
              </div>
              <div>
                <dt>Источники, ID</dt>
                <dd>{q.data.candidate_ids.join(", ") || "нет"}</dd>
              </div>
              <div>
                <dt>Выбранный рецепт</dt>
                <dd>{q.data.selected_recipe_id ?? "не выбран"}</dd>
              </div>
              <div>
                <dt>LLM</dt>
                <dd>{q.data.llm_called ? q.data.model : "не вызывалась"}</dd>
              </div>
            </dl>
            <h2>Путь запроса</h2>
            <ol className="stage-list">
              {q.data.stages.map((s, i) => (
                <li key={i}>
                  {s.status === "ok" ? (
                    <CheckCircle2 size={23} />
                  ) : s.status === "error" ? (
                    <AlertCircle size={23} />
                  ) : (
                    <MinusCircle size={23} />
                  )}
                  <div>
                    <strong>{s.name}</strong>
                    <small>
                      {s.status === "not_run"
                        ? "Не выполнялся"
                        : s.status === "error"
                          ? "Ошибка"
                          : "Выполнен"}
                    </small>
                  </div>
                  <span>
                    {s.duration_ms == null ? "—" : s.duration_ms + " мс"}
                  </span>
                </li>
              ))}
            </ol>
            {q.data.error_code && (
              <p className="error-box">Код ошибки: {q.data.error_code}</p>
            )}
          </>
        )
      )}
    </section>
  );
}
