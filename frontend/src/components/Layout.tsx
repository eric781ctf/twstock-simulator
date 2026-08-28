import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { isAuthenticated, username, logout } = useAuth();
  const navigate = useNavigate();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <>
      <header className="app-header">
        <h1>台股零股模擬交易</h1>
      </header>
      <nav className="navbar">
        <div className="nav-links">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            首頁
          </NavLink>
          <NavLink to="/trade" className={({ isActive }) => (isActive ? "active" : "")}>
            交易
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => (isActive ? "active" : "")}>
            交易紀錄
          </NavLink>
        </div>
        <div className="nav-user">
          <span>{username}</span>
          <button onClick={handleLogout}>登出</button>
        </div>
      </nav>
      <Outlet />
    </>
  );
}
