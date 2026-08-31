import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { isAuthenticated, nickname, username, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  function handleLogout() {
    setMenuOpen(false);
    logout();
    navigate("/login");
  }

  function handleLeaderboard() {
    setMenuOpen(false);
    navigate("/leaderboard");
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
          <NavLink to="/search" className={({ isActive }) => (isActive ? "active" : "")}>
            搜尋
          </NavLink>
          <NavLink to="/trade" className={({ isActive }) => (isActive ? "active" : "")}>
            交易
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => (isActive ? "active" : "")}>
            交易紀錄
          </NavLink>
          <NavLink to="/positions" className={({ isActive }) => (isActive ? "active" : "")}>
            部位
          </NavLink>
          <NavLink to="/strategy" className={({ isActive }) => (isActive ? "active" : "")}>
            策略
          </NavLink>
          <NavLink to="/tutorial" className={({ isActive }) => (isActive ? "active" : "")}>
            股市教學
          </NavLink>
        </div>
        <div className="nav-user" ref={menuRef}>
          <button className="nav-user-btn" onClick={() => setMenuOpen((open) => !open)}>
            {nickname ?? username}
            <span className={`nav-user-caret ${menuOpen ? "open" : ""}`}>▾</span>
          </button>
          {menuOpen && (
            <div className="nav-user-menu">
              <button onClick={handleLeaderboard}>排行榜</button>
              <button className="danger" onClick={handleLogout}>登出</button>
            </div>
          )}
        </div>
      </nav>
      <div key={location.pathname} className="page-transition">
        <Outlet />
      </div>
    </>
  );
}
