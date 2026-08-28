import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (username.trim().length < 3) {
      setError("帳號至少需要 3 個字元");
      return;
    }
    if (password.length < 6) {
      setError("密碼至少需要 6 個字元");
      return;
    }

    setSubmitting(true);
    try {
      await register(username, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "註冊失敗");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1>台股零股模擬交易</h1>
        <p className="auth-subtitle">建立新帳戶，起始資金 1,000,000 元</p>
        <input placeholder="帳號 (至少 3 字元)" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <input
          type="password"
          placeholder="密碼 (至少 6 字元)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="error-msg">{error}</div>}
        <button className="submit" type="submit" disabled={submitting}>
          {submitting ? "註冊中..." : "註冊並登入"}
        </button>
        <p className="auth-switch">
          已經有帳號？<Link to="/login">前往登入</Link>
        </p>
      </form>
    </div>
  );
}
