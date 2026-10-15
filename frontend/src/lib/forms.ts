import { z } from "zod";
export const credentialsSchema = z.object({
  email: z.string().trim().email("Введите корректный email"),
  password: z
    .string()
    .min(8, "Не менее 8 символов")
    .max(128, "Не более 128 символов"),
});
export const registrationSchema = credentialsSchema
  .extend({ confirmation: z.string() })
  .refine((v) => v.password === v.confirmation, {
    message: "Пароли не совпадают",
    path: ["confirmation"],
  });
export const userSchema = credentialsSchema.extend({
  role: z.enum(["user", "admin"]),
});

const rangeSchema = z
  .object({
    min: z.number().finite().nonnegative().nullable().optional(),
    max: z.number().finite().nonnegative().nullable().optional(),
  })
  .strict();
export const filtersSchema = z
  .object({
    kcal: rangeSchema.optional(),
    protein_g: rangeSchema.optional(),
    fat_g: rangeSchema.optional(),
    carbs_g: rangeSchema.optional(),
    max_total_time_minutes: z.number().int().positive().nullable().optional(),
  })
  .strict();
