import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "../api/services";
import { useAuth } from "../auth/Auth";
import { RagRecipeForm } from "./RagRecipeForm";
import type { SelectedRecipe } from "../api/types";
import { ErrorBox, Loading, PageTitle, Modal, Empty } from "../components/UI";
import { MAX_JSONL_BYTES } from "../lib/rag";
import type { RagRecipeInput } from "../lib/rag";

export function RagPage() {
  const { user } = useAuth();
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<SelectedRecipe | null>(null);
  const [deleting, setDeleting] = useState<SelectedRecipe | null>(null);
  const [editorEpoch, setEditorEpoch] = useState(0);
  const [notice, setNotice] = useState("");
  const [fileError, setFileError] = useState("");
  const [text, setText] = useState("");
  const [reading, setReading] = useState(false);
  const [uploadKey, setUploadKey] = useState(0);
  const editorRef = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["admin-rag", user!.user_id, offset], queryFn: ({ signal }) => adminApi.rag(offset, signal) });
  async function refresh(message: string) {
    setNotice(message);
    await Promise.all([
      client.invalidateQueries({ queryKey: ["admin-rag"] }),
      client.invalidateQueries({ queryKey: ["activity"] }),
    ]);
  }
  const save = useMutation({
    mutationFn: ({ input, original }: { input: RagRecipeInput; original: SelectedRecipe | null }) => original
      ? adminApi.updateRecipe(original.recipe_id, input, original.corpus_version)
      : adminApi.addRecipe(input),
    onSuccess: async (result, variables) => {
      setEditing(null);
      setEditorEpoch((v) => v + 1);
      validate.reset();
      await refresh(`Рецепт ${variables.original ? "обновлён" : "добавлен"}. Версия ${result.corpus_version}`);
    },
  });
  const remove = useMutation({
    mutationFn: (record: SelectedRecipe) => adminApi.deleteRecipe(record.recipe_id, record.corpus_version),
    onSuccess: async (result, record) => {
      setDeleting(null);
      if (editing?.recipe_id === record.recipe_id) { setEditing(null); setEditorEpoch((v) => v + 1); save.reset(); }
      if (offset && q.data?.items.length === 1) setOffset((v) => Math.max(0, v - 20));
      validate.reset();
      await refresh(`Рецепт удалён. Версия ${result.corpus_version}`);
    },
  });
  const validate = useMutation({ mutationFn: async (value: string) => ({ text: value, report: await adminApi.validateImport(value) }) });
  const upload = useMutation({
    mutationFn: (value: string) => adminApi.importRecipes(value),
    onSuccess: async (result) => {
      setText("");
      setUploadKey((v) => v + 1);
      validate.reset();
      await refresh(`Добавлено записей: ${result.added}. Версия ${result.corpus_version}`);
    },
  });
  const busy = reading || save.isPending || remove.isPending || validate.isPending || upload.isPending;
  const report = validate.data?.text === text ? validate.data.report : null;
  return (
    <section>
      <PageTitle title="Данные RAG">Добавляйте, редактируйте и удаляйте рецепты или загружайте JSONL.</PageTitle>
      <p className="muted">Демонстрационные данные и поиск. Настоящий BM25 и LLM не вызываются.</p>
      {notice && <p className="success-notice" role="status">{notice}</p>}
      <div className="rag-panels">
        <div ref={editorRef} className="rag-editor">
          <RagRecipeForm key={`${editing?.recipe_id ?? "new"}-${editorEpoch}`}
            initial={editing} disabled={busy} saving={save.isPending} error={save.error}
            onSave={(input) => { setNotice(""); save.reset(); save.mutate({ input, original: editing }); }}
            onCancel={() => { setEditing(null); setEditorEpoch((v) => v + 1); save.reset(); }} />
        </div>
        <div className="rag-panel">
          <h2>Импорт JSONL</h2>
          <p className="muted">Один рецепт на строку. До 5 МиБ и 1000 записей. Ошибки и дубликаты блокируют весь импорт.</p>
          <label>Файл JSONL<input key={uploadKey} type="file" accept=".jsonl,.ndjson,application/x-ndjson" disabled={busy} onChange={async (e) => {
            const file = e.target.files?.[0];
            setText(""); setNotice(""); setFileError(""); validate.reset(); upload.reset();
            if (!file) return;
            if (file.size > MAX_JSONL_BYTES) { setFileError("Файл превышает 5 МиБ"); return; }
            setReading(true);
            try { setText(await file.text()); } catch { setFileError("Не удалось прочитать файл. Выберите его ещё раз."); }
            finally { setReading(false); }
          }} /></label>
          <details><summary>Пример строки</summary><pre className="rag-example">{'{"title":"Гречка с грибами","ingredients":[{"name":"Гречка"},{"name":"Грибы","amount":"200 г"}],"url":"https://example.org/recipe"}'}</pre></details>
          <div className="rag-actions">
            <button className="button secondary" disabled={busy || !text} onClick={() => validate.mutate(text)}>Проверить файл</button>
            <button className="button primary" disabled={busy || !report?.valid} onClick={() => { setNotice(""); upload.mutate(text); }}>Подтвердить импорт</button>
          </div>
          {fileError && <p className="field-error" role="alert">{fileError}</p>}
          {validate.error && <ErrorBox error={validate.error} />}
          {upload.error && <ErrorBox error={upload.error} />}
          {report && <div role="status" className="rag-report">
            <p>Записей: {report.count} · Ошибок: {report.errors.length} · Дубликатов: {report.duplicates.length}</p>
            {report.valid && <p>Файл готов к импорту.</p>}
            {!!report.errors.length && <ul>{report.errors.map((e, i) => <li key={i}>Строка {e.line}: {e.message}</li>)}</ul>}
            {!!report.duplicates.length && <ul>{report.duplicates.map((e, i) => <li key={i}>Строка {e.line}: {e.message}</li>)}</ul>}
          </div>}
        </div>
      </div>
      <div className="section-toolbar"><h2>Рецепты демокорпуса</h2>
        <button className="button secondary" disabled={busy || q.isFetching} onClick={() => void q.refetch()}>Обновить список</button>
      </div>
      {q.isPending ? <Loading /> : q.error ? <ErrorBox error={q.error} onRetry={() => void q.refetch()} /> : <>
        <p className="muted">{q.data.total} записей · Версия {q.data.corpus_version}</p>
        {!q.data.total && <Empty title="В каталоге пока нет рецептов">Добавьте рецепт формой или импортируйте JSONL.</Empty>}
        {!!q.data.items.length && <div className="table-wrap"><table>
          <thead><tr><th>ID</th><th>Название</th><th>Источник</th><th>Шаги</th><th>Действия</th></tr></thead>
          <tbody>{q.data.items.map((r) => <tr key={r.recipe_id}><td>{r.recipe_id}</td><td>{r.title}</td><td><a href={r.url} target="_blank" rel="noreferrer">Открыть источник</a></td><td>{r.steps.length ? `${r.steps.length} (демо)` : "Нет данных"}</td><td><div className="rag-row-actions">
            <button className="text-button" disabled={busy || q.isFetching} aria-label={`Редактировать ${r.title}`} onClick={() => {
              save.reset(); setNotice(""); setEditing(r); setEditorEpoch((v) => v + 1);
              editorRef.current?.scrollIntoView({ block: "start" });
            }}>Редактировать</button>
            <button className="text-button" disabled={busy || q.isFetching} aria-label={`Удалить ${r.title}`} onClick={() => { remove.reset(); setDeleting(r); }}>Удалить</button>
          </div></td></tr>)}</tbody>
        </table></div>}
        <div className="pagination"><span className="muted">Показано {q.data.items.length} из {q.data.total}</span>
          <button className="button secondary" disabled={!offset} onClick={() => setOffset((v) => Math.max(0, v - 20))}>Назад</button>
          <button className="button secondary" disabled={offset + 20 >= q.data.total} onClick={() => setOffset((v) => v + 20)}>Далее</button>
        </div>
      </>}
      {deleting && <Modal title="Удалить рецепт?" onClose={() => { if (!remove.isPending) setDeleting(null); }}>
        <p>Удалить «{deleting.title}» из каталога? Новые подборы больше не найдут этот рецепт. Сохранённые чаты останутся доступны.</p>
        {remove.error && <ErrorBox error={remove.error} />}
        <div className="dialog-actions">
          <button className="button secondary" disabled={remove.isPending} onClick={() => setDeleting(null)}>Отмена</button>
          <button className="button primary" disabled={remove.isPending} onClick={() => remove.mutate(deleting)}>{remove.isPending ? "Удаляем…" : "Удалить"}</button>
        </div>
      </Modal>}
    </section>
  );
}
