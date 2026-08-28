import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "../api";

const USERNAME_KEY = "twstock_username";

interface AuthContextValue {
  username: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem(USERNAME_KEY));
  const [tokenPresent, setTokenPresent] = useState<boolean>(() => !!getToken());

  useEffect(() => {
    function handleUnauthorized() {
      setToken(null);
      localStorage.removeItem(USERNAME_KEY);
      setUsername(null);
      setTokenPresent(false);
    }
    window.addEventListener("twstock:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("twstock:unauthorized", handleUnauthorized);
  }, []);

  async function login(user: string, password: string) {
    const res = await api.login(user, password);
    setToken(res.access_token);
    localStorage.setItem(USERNAME_KEY, res.username);
    setUsername(res.username);
    setTokenPresent(true);
  }

  async function register(user: string, password: string) {
    const res = await api.register(user, password);
    setToken(res.access_token);
    localStorage.setItem(USERNAME_KEY, res.username);
    setUsername(res.username);
    setTokenPresent(true);
  }

  function logout() {
    setToken(null);
    localStorage.removeItem(USERNAME_KEY);
    setUsername(null);
    setTokenPresent(false);
  }

  return (
    <AuthContext.Provider value={{ username, isAuthenticated: tokenPresent, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
