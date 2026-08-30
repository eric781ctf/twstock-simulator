import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "../api";

const USERNAME_KEY = "twstock_username";
const NICKNAME_KEY = "twstock_nickname";

interface AuthContextValue {
  username: string | null;
  nickname: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, nickname: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem(USERNAME_KEY));
  const [nickname, setNickname] = useState<string | null>(() => localStorage.getItem(NICKNAME_KEY));
  const [tokenPresent, setTokenPresent] = useState<boolean>(() => !!getToken());

  useEffect(() => {
    function handleUnauthorized() {
      setToken(null);
      localStorage.removeItem(USERNAME_KEY);
      localStorage.removeItem(NICKNAME_KEY);
      setUsername(null);
      setNickname(null);
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
    setUsername(res.username);
    setNickname(res.nickname);
    setTokenPresent(true);
  }

  async function register(user: string, password: string, nick: string) {
    const res = await api.register(user, password, nick);
    setToken(res.access_token);
    localStorage.setItem(USERNAME_KEY, res.username);
    localStorage.setItem(NICKNAME_KEY, res.nickname);
    setUsername(res.username);
    setNickname(res.nickname);
    setTokenPresent(true);
  }

  function logout() {
    setToken(null);
    localStorage.removeItem(USERNAME_KEY);
    localStorage.removeItem(NICKNAME_KEY);
    setUsername(null);
    setNickname(null);
    setTokenPresent(false);
  }

  return (
    <AuthContext.Provider value={{ username, nickname, isAuthenticated: tokenPresent, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
