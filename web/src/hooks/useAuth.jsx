/**
 * Authentication context
 * ======================
 * Who is signed in, what they may do, and one place that handles a session
 * ending.
 *
 * `can(capability)` mirrors the server's capability matrix exactly. It exists
 * to keep the interface honest — hiding a button the server would refuse is
 * kinder than showing it and failing — but it is never the enforcement. The
 * server checks every request through the Authorisation Agent regardless, so a
 * bug here is a cosmetic problem rather than a security one.
 */
import * as React from "react";
import { api, ApiError } from "@/lib/api";

const AuthContext = React.createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = React.useState(null);
  const [roles, setRoles] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [signInInfo, setSignInInfo] = React.useState(null);

  const refresh = React.useCallback(async () => {
    try {
      const data = await api.session();
      setUser(data.authenticated ? data.user : null);
      setRoles(data.roles || []);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const login = React.useCallback(async (username, password) => {
    const data = await api.login(username, password);
    setUser(data.user);
    // The Authentication Agent's risk signals are worth surfacing once, on the
    // dashboard, rather than discarding: "first sign-in from this address" is
    // exactly the kind of thing someone should see.
    setSignInInfo({ risk: data.risk, signals: data.signals || [] });
    await refresh();
    return data;
  }, [refresh]);

  const logout = React.useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setSignInInfo(null);
    }
  }, []);

  const can = React.useCallback(
    (capability) => Boolean(user?.capabilities?.includes(capability)),
    [user]
  );

  /** Wrap a call so an expired session logs out once instead of erroring on
   *  every screen that happens to be mounted. */
  const guard = React.useCallback(
    async (fn) => {
      try {
        return await fn();
      } catch (err) {
        if (err instanceof ApiError && err.unauthenticated) setUser(null);
        throw err;
      }
    },
    []
  );

  const value = React.useMemo(
    () => ({
      user,
      roles,
      loading,
      signInInfo,
      dismissSignInInfo: () => setSignInInfo(null),
      login,
      logout,
      refresh,
      can,
      guard,
      isAdmin: user?.role === "admin",
    }),
    [user, roles, loading, signInInfo, login, logout, refresh, can, guard]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside an AuthProvider.");
  return ctx;
}
