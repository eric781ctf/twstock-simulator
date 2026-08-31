import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "../api";

const USERNAME_KEY = "twstock_username";
const NICKNAME_KEY = "twstock_nickname";
const IS_ADMIN_KEY = "twstock_is_admin";

interface AuthContextValue {
  username: string | null;
  nickname: string | null;
  isAdmin: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, nickname: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem(USERNAME_KEY));
  const [nickname, setNickname] = useState<string | null>(() => localStorage.getItem(NICKNAME_KEY));
  const [isAdmin, setIsAdmin] = useState<boolean>(() => localStorage.getItem(IS_ADMIN_KEY) === "true");
  const [tokenPresent, setTokenPresent] = useState<boolean>(() => !!getToken());

  useEffect(() => {
    function handleUnauthorized() {
      setToken(null);
      localStorage.removeItem(USERNAME_KEY);
      localStorage.removeItem(NICKNAME_KEY);
      localStorage.removeItem(IS_ADMIN_KEY);
      setUsername(null);
      setNickname(null);
      setIsAdmin(false);
      setTokenPresent(false);
    }
    window.addEventListener("twstock:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("twstock:unauthorized", handleUnauthorized);
  }, []);

  async function login(user: string, password: string) {
    const res = await api.login(user, password);
    setToken(res.access_token);
    localStorage.setItem(USERNAME_KEY, res.username);
    localStorage.setItem(NICKNAME_KEY, res.nickname);
    localStorage.setItem(IS_ADMIN_KEY, String(res.is_admin));
    setUsername(res.username);
    setNickname(res.nickname);
    setIsAdmin(res.is_admin);
    setTokenPresent(true);
  }

  async function register(user: string, password: string, nick: string) {
    const res = await api.register(user, password, nick);
    setToken(res.access_token);
    localStorage.setItem(USERNAME_KEY, res.username);
    localStorage.setItem(NICKNAME_KEY, res.nickname);
    localStorage.setItem(IS_ADMIN_KEY, String(res.is_admin));
    setUsername(res.username);
    setNickname(res.nickname);
    setIsAdmin(res.is_admin);
    setTokenPresent(true);
  }

  function logout() {
    setToken(null);
    localStorage.removeItem(USERNAME_KEY);
    localStorage.removeItem(NICKNAME_KEY);
    localStorage.removeItem(IS_ADMIN_KEY);
    setUsername(null);
    setNickname(null);
    setIsAdmin(false);
    setTokenPresent(false);
  }

  return (
    <AuthContext.Provider value={{ username, nickname, isAdmin, isAuthenticated: tokenPresent, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
