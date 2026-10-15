import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight } from "lucide-react";
import { Brand, Sage } from "../components/Brand";
import { ErrorBox } from "../components/UI";
import { authApi } from "../api/services";
import { credentialsSchema, registrationSchema } from "../lib/forms";
import { setSignedIn, useAuth } from "../auth/Auth";
type Fields = { email: string; password: string; confirmation?: string };
export function AuthPage({ register = false }: { register?: boolean }) {
  const a = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState(false);
  const form = useForm<Fields>({
    resolver: zodResolver(register ? registrationSchema : credentialsSchema),
    defaultValues: { email: "", password: "", confirmation: "" },
  });
  if (a.user) return <Navigate to="/chat" replace />;
  async function submit(v: Fields) {
    setError(null);
    try {
      if (register) {
        await authApi.register(v.email, v.password);
        setSuccess(true);
        form.reset();
      } else {
        const u = await authApi.login(v.email, v.password);
        await setSignedIn(u);
        const from = location.state?.from;
        void navigate(
          typeof from === "string" &&
            from.startsWith("/") &&
            !from.startsWith("//")
            ? from
            : "/chat",
          { replace: true },
        );
      }
    } catch (e) {
      setError(e);
    }
  }
  return (
    <main className="auth-page">
      <aside className="auth-story">
        <Brand />
        <h1>
          Хороший ужин
          <br />
          начинается с того,
          <br />
          что уже есть.
        </h1>
        <Sage />
        <p>
          Ваши продукты.
          <br />
          Немного вдохновения.
          <br />
          Понятный рецепт.
        </p>
        <small>ИИ-шеф — помощник на вашей кухне</small>
      </aside>
      <section className="auth-form-area">
        <div className="auth-form-wrap">
          <Brand />
          <h2>{register ? "Давайте знакомиться" : "С возвращением"}</h2>
          <p className="muted">
            {register
              ? "Создайте аккаунт, чтобы начать готовить."
              : "Войдите, чтобы найти идею для ужина."}
          </p>
          {success ? (
            <div className="success-box" role="status">
              <h3>Аккаунт создан</h3>
              <p>Теперь можно войти со своим email и паролем.</p>
              <Link className="button primary" to="/login">
                Перейти ко входу <ArrowRight size={17} />
              </Link>
            </div>
          ) : (
            <form onSubmit={form.handleSubmit(submit)} noValidate>
              <label>
                Электронная почта
                <input
                  type="email"
                  autoComplete="email"
                  placeholder="name@example.ru"
                  {...form.register("email")}
                  aria-invalid={!!form.formState.errors.email}
                />
                <span className="field-error">
                  {form.formState.errors.email?.message}
                </span>
              </label>
              <label>
                Пароль
                <input
                  type="password"
                  autoComplete={register ? "new-password" : "current-password"}
                  placeholder="Введите пароль"
                  {...form.register("password")}
                  aria-invalid={!!form.formState.errors.password}
                />
                <span className="field-error">
                  {form.formState.errors.password?.message}
                </span>
              </label>
              {register && (
                <label>
                  Повторите пароль
                  <input
                    type="password"
                    autoComplete="new-password"
                    placeholder="Введите пароль ещё раз"
                    {...form.register("confirmation")}
                  />
                  <span className="field-error">
                    {form.formState.errors.confirmation?.message}
                  </span>
                </label>
              )}
              {!!error && <ErrorBox error={error} />}
              <button
                className="button primary full"
                disabled={form.formState.isSubmitting}
              >
                {form.formState.isSubmitting
                  ? "Подождите…"
                  : register
                    ? "Создать аккаунт"
                    : "Войти"}
                <ArrowRight size={17} />
              </button>
            </form>
          )}
          <Link className="auth-switch" to={register ? "/login" : "/register"}>
            {register
              ? "Уже есть аккаунт? Войти"
              : "Нет аккаунта? Зарегистрироваться"}
          </Link>
          <small className="muted">
            Продукты, рецепты и помощь — в одном месте.
          </small>
        </div>
      </section>
    </main>
  );
}
