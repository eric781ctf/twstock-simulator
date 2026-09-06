import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登入失敗");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card page-transition" onSubmit={handleSubmit}>
        <h1>台股 AI 預測模型系統</h1>
        <p className="auth-subtitle">管理員登入</p>
        <input placeholder="帳號" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <input
          type="password"
          placeholder="密碼"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="error-msg">{error}</div>}
        <button className="submit" type="submit" disabled={submitting}>
          {submitting ? "登入中..." : "登入"}
        </button>
      </form>
    </div>
  );
}
