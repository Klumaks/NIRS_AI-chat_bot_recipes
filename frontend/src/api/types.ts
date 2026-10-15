export type Role = "user" | "admin";
export interface User {
  user_id: string;
  email: string;
  role: Role;
  created_at?: string;
}
export type NutritionKey = "kcal" | "protein_g" | "fat_g" | "carbs_g";
export type Nutrition = Record<NutritionKey, number | null>;
export interface Filters {
  kcal?: Range;
  protein_g?: Range;
  fat_g?: Range;
  carbs_g?: Range;
  max_total_time_minutes?: number | null;
}
export interface Range {
  min?: number | null;
  max?: number | null;
}
export interface Recipe {
  recipe_id: number;
  title: string;
  description: string | null;
  ingredients: { name: string; amount: string | null }[];
  url: string;
  nutrition_per_100g: Nutrition;
  total_time_minutes: number | null;
  difficulty: "easy" | "medium" | "hard" | null;
  missing_ingredients: string[];
  provenance: Record<
    string,
    {
      source_ref: string;
      method: string;
      checked_by: string;
      checked_at: string;
    }
  >;
  data_mode: "demo" | "verified";
}
export interface SelectedRecipe extends Recipe {
  steps: string[];
  corpus_version: string;
  verified_version: string;
}
export interface Selection {
  chat_id: string;
  selection_id: string;
  corpus_version: string;
  filters: Filters;
  items: Recipe[];
  total: number;
  request_id: string;
}
export interface Message {
  message_id: string;
  role: "user" | "assistant";
  text: string;
  created_at: string;
  conversation_id?: string;
  recipe_id?: number;
  sources?: { recipe_id: number; url: string; step_numbers: number[] }[];
}
export interface ChatSummary {
  chat_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface Chat extends ChatSummary {
  messages: Message[];
  selection_id: string;
  products_text: string;
  filters: Filters;
  selected_recipe: SelectedRecipe | null;
  conversation_id: string | null;
  resume_status: "ready" | "recipe_unavailable";
  selection: Selection;
}
export interface Activity {
  occurred_at: string;
  user_id: string | null;
  event_type: string;
  status: string;
  duration_ms: number | null;
  request_id: string;
  target_user_id?: string;
  assigned_role?: Role;
}
export interface Diagnostic {
  request_id: string;
  corpus_version: string | null;
  index_version: string | null;
  normalization_mode: string | null;
  candidate_ids: number[];
  selected_recipe_id: number | null;
  llm_called: boolean;
  model: string | null;
  error_code: string | null;
  stages: { name: string; status: string; duration_ms: number | null }[];
}
export interface List<T> {
  items: T[];
  total: number;
  request_id: string;
}
export interface Answer {
  chat_id: string;
  message_id: string;
  answer: string;
  sources: { recipe_id: number; url: string; step_numbers: number[] }[];
  status: "answered" | "insufficient_context";
  request_id: string;
}
export interface RecipeResponse extends SelectedRecipe {
  chat_id: string;
  conversation_id: string;
  request_id: string;
}
