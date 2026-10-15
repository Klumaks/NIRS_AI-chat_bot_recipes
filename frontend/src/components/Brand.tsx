export function Brand({ large = false }: { large?: boolean }) {
  return (
    <span className={"brand" + (large ? " brand-large" : "")}>
      <img src="/brand-sage.svg" alt="" width="38" height="38" />
      <span>ИИ-шеф</span>
    </span>
  );
}
export function Sage({ className = "" }: { className?: string }) {
  return (
    <img
      className={"sage " + className}
      src="/brand-sage.svg"
      alt=""
      width="160"
      height="160"
    />
  );
}
