import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import type { User } from "../api/types";
import { authApi } from "../api/services";
import { ApiError } from "../api/client";
import { queryClient } from "../lib/query";
import { Loading, ErrorBox } from "../components/UI";
const AuthContext = createContext<{
  user: User | undefined;
  loading: boolean;
  error: unknown;
  reload: () => void;
}>({ user: undefined, loading: true, error: null, reload: () => {} });
export function AuthProvider({ children }: { children: ReactNode }) {
  const q = useQuery({
    queryKey: ["auth"],
    queryFn: ({ signal }) => authApi.me(signal),
    retry: false,
    staleTime: 30_000,
  });
  const expired = q.error instanceof ApiError && q.error.status === 401;
  return (
    <AuthContext.Provider
      value={{
        user: expired ? undefined : q.data,
        loading: q.isPending,
        error: q.error,
        reload: () => {
          void q.refetch();
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export const useAuth = () => useContext(AuthContext);
export async function setSignedIn(user: User) {
  await queryClient.cancelQueries();
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
  queryClient.setQueryData(["auth"], user);
}
export function Protected({
  children,
  admin = false,
}: {
  children: ReactNode;
  admin?: boolean;
}) {
  const a = useAuth();
  const l = useLocation();
  if (a.loading) return <Loading />;
  if (!a.user) {
    if (a.error instanceof ApiError && a.error.status !== 401)
      return (
        <main className="standalone">
          <ErrorBox error={a.error} onRetry={a.reload} />
        </main>
      );
    return <Navigate to="/login" state={{ from: l.pathname }} replace />;
  }
  if (admin && a.user.role !== "admin") return <Navigate to="/403" replace />;
  return children;
}
