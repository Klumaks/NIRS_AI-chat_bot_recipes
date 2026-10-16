/** Split ingredient labels without breaking multiword names or words containing и. */
export function splitProducts(text: string): string[] {
  return text.split(/[,;]+|(?:^|\s)и(?=\s|$)/iu).map((s) => s.trim()).filter(Boolean);
}
