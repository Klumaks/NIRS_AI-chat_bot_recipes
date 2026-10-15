import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowLeft,
  Send,
  SlidersHorizontal,
  Clock3,
} from "lucide-react";
import { chatApi } from "../api/services";
import type { Chat, Filters } from "../api/types";
import { useAuth } from "../auth/Auth";
import { queryClient } from "../lib/query";
import { Sage } from "../components/Brand";
import { Loading, ErrorBox, Empty } from "../components/UI";
import { RecipeCard, Nutrition } from "../components/RecipeCard";
import { FilterPanel } from "../components/FilterPanel";
import { difficultyLabel, nutritionFields } from "../lib/filters";
import { rememberChat, forgetChat } from "../lib/lastChat";
import { ApiError } from "../api/client";
function Composer({
  placeholder,
  label,
  value,
  onChange,
  onSubmit,
  pending,
}: {
  placeholder: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  pending: boolean;
}) {
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <label className="sr-only" htmlFor="message-input">
        {label}
      </label>
      <input
        id="message-input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={2000}
        disabled={pending}
        autoComplete="off"
      />
      <button className="button primary" disabled={pending || !value.trim()}>
        {pending ? "Подождите…" : "Отправить"}
        <Send size={17} />
      </button>
    </form>
  );
}
export function ChatPage() {
  const { chatId, recipeId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [question, setQuestion] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [inputError, setInputError] = useState("");
  const pendingQuestion = useRef<{ text: string; id: string } | null>(null);
  const chatKey = ["chat", user!.user_id, chatId];
  const q = useQuery({
    queryKey: chatKey,
    queryFn: ({ signal }) => chatApi.detail(chatId!, signal),
    enabled: !!chatId,
  });
  const chat = q.data;
  useEffect(() => {
    if (chatId && q.error instanceof ApiError && q.error.status === 404) {
      forgetChat(user!.user_id, chatId);
      return;
    }
    if (!chatId || !q.data || q.error) return;
    if (recipeId && q.data.selected_recipe?.recipe_id !== Number(recipeId)) return;
    rememberChat(user!.user_id, "/chat/" + encodeURIComponent(chatId) + (recipeId ? "/recipe/" + recipeId : ""));
  }, [chatId, recipeId, q.data, q.error, user]);

  useEffect(() => {
    setText("");
    setQuestion("");
    setFiltersOpen(false);
    setInputError("");
    pendingQuestion.current = null;
  }, [chatId, recipeId]);
  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: chatKey }),
      queryClient.invalidateQueries({ queryKey: ["chats", user!.user_id] }),
    ]);
  }
  const create = useMutation({
    mutationFn: chatApi.create,
    onSuccess: async (result) => {
      setText("");
      await queryClient.invalidateQueries({
        queryKey: ["chats", user!.user_id],
      });
      void navigate("/chat/" + result.chat_id);
    },
  });
  const filter = useMutation({
    mutationFn: (f: Filters) => chatApi.filter(chat!.selection_id, f),
    onSuccess: async () => {
      await refresh();
      setFiltersOpen(false);
    },
  });
  const select = useMutation({
    mutationFn: (id: number) => chatApi.select(chat!.selection_id, id),
    onSuccess: async (result) => {
      await refresh();
      void navigate("/chat/" + result.chat_id + "/recipe/" + result.recipe_id);
    },
  });
  const ask = useMutation({
    mutationFn: ({
      text,
      id,
      conversation,
    }: {
      text: string;
      id: string;
      conversation: string;
    }) => chatApi.message(conversation, id, text),
    onSuccess: async () => {
      pendingQuestion.current = null;
      setQuestion("");
      await refresh();
    },
  });
  function search() {
    setInputError("");
    if (!text.trim()) {
      setInputError("Перечислите продукты.");
      return;
    }
    create.mutate(text.trim());
  }
  function send() {
    if (!question.trim() || !chat?.conversation_id) return;
    if (
      !pendingQuestion.current ||
      pendingQuestion.current.text !== question.trim()
    )
      pendingQuestion.current = {
        text: question.trim(),
        id: crypto.randomUUID(),
      };
    ask.mutate({
      ...pendingQuestion.current,
      conversation: chat.conversation_id,
    });
  }
  if (chatId && q.isPending) return <Loading />;
  if (chatId && q.error)
    return (
      <>
        <ErrorBox error={q.error} onRetry={() => void q.refetch()} />
        <Link className="button secondary" to="/chat">
          Новый подбор
        </Link>
      </>
    );
  if (!chatId)
    return (
      <section className="welcome">
        <h1>Что приготовим сегодня?</h1>
        <p className="welcome-description">
          Расскажите, что есть дома. ИИ-шеф предложит блюда
          <br className="desktop-break" /> и поможет разобраться с рецептом.
        </p>
        <Sage />
        <div className="suggestion-box">
          <h2>Попробуйте, например</h2>
          <div className="example-buttons">
            <button
              className="chip"
              onClick={() => {
                setText("Курица, рис, лук");
                document.getElementById("message-input")?.focus();
              }}
            >
              Курица, рис, лук
            </button>
            <button
              className="chip"
              onClick={() => {
                setText("Яйца и помидоры");
                document.getElementById("message-input")?.focus();
              }}
            >
              Яйца и помидоры
            </button>
          </div>
        </div>
        <p className="muted">
          Можно будет уточнить калории, БЖУ и время приготовления.
        </p>
        {inputError && (
          <p className="field-error" role="alert">
            {inputError}
          </p>
        )}
        {create.error && <ErrorBox error={create.error} onRetry={search} />}
        <Composer
          placeholder="Например: курица, рис и лук…"
          label="Ваши продукты"
          value={text}
          onChange={setText}
          onSubmit={search}
          pending={create.isPending}
        />
      </section>
    );
  if (!chat) return null;
  if (recipeId) {
    if (
      !chat.selected_recipe ||
      chat.selected_recipe.recipe_id !== Number(recipeId)
    )
      return (
        <>
          <Empty title="Рецепт не выбран в этом чате">
            <Link to={"/chat/" + chatId}>Вернуться к предложениям</Link>
          </Empty>
        </>
      );
    return (
      <RecipeView
        chat={chat}
        question={question}
        setQuestion={setQuestion}
        send={send}
        pending={ask.isPending}
        error={ask.error}
      />
    );
  }
  const active = Object.entries(chat.filters).length > 0;
  return (
    <section>
      <div className="page-title">
        <h1>Подберём что-нибудь вкусное</h1>
        <Link className="text-button" to="/chat">
          <ArrowLeft size={16} />
          Изменить продукты
        </Link>
      </div>
      <p className="muted">Вы написали: «{chat.products_text}»</p>
      <div className="product-chips">
        {chat.products_text
          .split(/[,;]+/)
          .slice(0, 8)
          .map((s, i) => (
            <span className="chip" key={i}>
              {s.trim()}
            </span>
          ))}
      </div>
      <div className="results-heading">
        <h2>Вот несколько идей для ужина</h2>
        <button
          className="button secondary"
          onClick={() => setFiltersOpen(!filtersOpen)}
        >
          <SlidersHorizontal size={17} />
          Фильтры{active ? " · применены" : ""}
        </button>
      </div>
      <p className="muted small">
        Можно приготовить с небольшими дополнениями к вашим продуктам.
      </p>
      {active && (
        <div className="active-filters">
          {nutritionFields.map(
            ([k, label]) =>
              chat.filters[k] &&
              (chat.filters[k]!.min != null ||
                chat.filters[k]!.max != null) && (
                <span className="chip" key={k}>
                  {label}: {chat.filters[k]!.min ?? "…"}–
                  {chat.filters[k]!.max ?? "…"}
                </span>
              ),
          )}
          {chat.filters.max_total_time_minutes != null && (
            <span className="chip">
              До {chat.filters.max_total_time_minutes} мин
            </span>
          )}
          <button className="text-button" onClick={() => filter.mutate({})}>
            Сбросить всё
          </button>
        </div>
      )}
      {filter.error && <ErrorBox error={filter.error} />}
      <div className={"results-layout " + (filtersOpen ? "with-filters" : "")}>
        {filtersOpen && (
          <>
            <button
              className="filter-backdrop"
              aria-label="Закрыть фильтры"
              onClick={() => setFiltersOpen(false)}
            />
            <FilterPanel
              filters={chat.filters}
              onApply={(f) => filter.mutate(f)}
              onClose={() => setFiltersOpen(false)}
              pending={filter.isPending}
            />
          </>
        )}
        <div className="results-main">
          {select.error && <ErrorBox error={select.error} />}
          <div className="recipes-grid">
            {chat.selection.items.map((r, i) => (
              <RecipeCard
                key={r.recipe_id}
                recipe={r}
                index={i}
                onSelect={() => select.mutate(r.recipe_id)}
                disabled={select.isPending}
              />
            ))}
          </div>
          {!chat.selection.items.length && (
            <Empty
              title={
                active ? "Пока ничего не подходит" : "Не нашли подходящих блюд"
              }
            >
              {active ? (
                <>
                  <p>Попробуйте ослабить ограничения по КБЖУ или времени.</p>
                  <button
                    className="button secondary"
                    onClick={() => filter.mutate({})}
                  >
                    Сбросить фильтры
                  </button>
                </>
              ) : (
                <Link to="/chat">Изменить продукты</Link>
              )}
            </Empty>
          )}
          <p className="muted small">
            {chat.selection.total} блюд найдено · показано до пяти. Недостающие
            ингредиенты указаны в карточках.
          </p>
          {chat.selected_recipe && (
            <Link
              className="button secondary"
              to={
                "/chat/" +
                chat.chat_id +
                "/recipe/" +
                chat.selected_recipe.recipe_id
              }
            >
              Продолжить выбранный рецепт <ArrowRight size={17} />
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
function RecipeView({
  chat,
  question,
  setQuestion,
  send,
  pending,
  error,
}: {
  chat: Chat;
  question: string;
  setQuestion: (s: string) => void;
  send: () => void;
  pending: boolean;
  error: unknown;
}) {
  const r = chat.selected_recipe!;
  const current = chat.messages.filter(
    (m) => m.conversation_id === chat.conversation_id,
  );
  const old = chat.messages.filter(
    (m) => m.conversation_id && m.conversation_id !== chat.conversation_id,
  );
  return (
    <section className="recipe-view">
      <Link className="text-button back-link" to={"/chat/" + chat.chat_id}>
        <ArrowLeft size={17} />К предложениям
      </Link>
      <h1>{r.title}</h1>
      <p className="muted">{r.description || "Описание: нет данных"}</p>
      <div className="product-chips">
        <span className="chip">
          <Clock3 size={15} />
          {r.total_time_minutes == null
            ? "Время: нет данных"
            : r.total_time_minutes + " минут"}
        </span>
        <span className="chip">{difficultyLabel(r.difficulty)}</span>
        <span className="chip">
          {r.nutrition_per_100g.kcal == null
            ? "нет данных"
            : r.nutrition_per_100g.kcal + " ккал / 100 г"}
        </span>
      </div>
      <Nutrition recipe={r} />
      <div className="recipe-columns">
        <section className="ingredients-panel">
          <h2>Ингредиенты</h2>
          <ul>
            {r.ingredients.map((i, n) => (
              <li key={n}>
                <span>{i.name}</span>
                <span>{i.amount || "количество не указано"}</span>
              </li>
            ))}
          </ul>
          <p className="missing">
            Не хватает:{" "}
            {r.missing_ingredients.join(", ") || "все продукты есть"}
          </p>
          <small className="muted">Количество запасов не проверяется.</small>
        </section>
        <section className="steps-panel">
          <h2>Как приготовить</h2>
          <ol>
            {r.steps.map((s, i) => (
              <li key={i}>
                <span className="step-number">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <p>{s}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
      <p className="source-note">
        <a href={r.url} target="_blank" rel="noreferrer">
          Источник рецепта
        </a>{" "}
        ·{" "}
        {r.data_mode === "demo"
          ? "демонстрационные данные"
          : "проверенные данные"}{" "}
        · версия {r.verified_version}
      </p>
      {old.length > 0 && (
        <details className="archived-messages">
          <summary>Предыдущие вопросы по другим блюдам ({old.length})</summary>
          {old.map((m) => (
            <p key={m.message_id}>
              <strong>{m.role === "user" ? "Вы" : "ИИ-шеф"}:</strong> {m.text}
            </p>
          ))}
        </details>
      )}
      <section className="conversation">
        <h2>Готовим вместе</h2>
        <p className="muted">Задайте вопрос по выбранному рецепту.</p>
        <div className="messages" aria-live="polite">
          {current.map((m) => (
            <div className={"message " + m.role} key={m.message_id}>
              <strong>{m.role === "user" ? "Вы" : "ИИ-шеф"}</strong>
              <p>{m.text}</p>
              {m.sources?.map((s, i) => (
                <a key={i} href={s.url} target="_blank" rel="noreferrer">
                  Источник · шаг {s.step_numbers.join(", ")}
                </a>
              ))}
            </div>
          ))}
          {pending && (
            <p role="status" className="muted">
              Помощник готовит ответ…
            </p>
          )}
        </div>
        {chat.resume_status === "recipe_unavailable" ? (
          <Empty title="Сохранённый рецепт доступен для чтения">
            <p>Продолжить этот контекст нельзя. Переписка сохранена.</p>
            <Link className="button secondary" to="/chat">
              Новый подбор
            </Link>
          </Empty>
        ) : (
          <>
            {!!error && <ErrorBox error={error} onRetry={send} />}
            <Composer
              placeholder="Вопрос по этому рецепту…"
              label="Вопрос по рецепту"
              value={question}
              onChange={setQuestion}
              onSubmit={send}
              pending={pending}
            />
          </>
        )}
      </section>
    </section>
  );
}
