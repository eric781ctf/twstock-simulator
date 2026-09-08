import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

// 這個系統不再有一般使用者帳號，只有 admin 需要登入來訓練/管理模型。
// 所有公開頁面（模型列表、股市教學）不需要登入即可瀏覽，admin 登入後
// 一樣可以逛公開頁面，不會被鎖在管理後台裡出不來。
export function Layout() {
  const { isAuthenticated, nickname, username, isAdmin, logout } = useAuth();
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

  function handleLogout() {
    setMenuOpen(false);
    logout();
    navigate("/");
  }

  return (
    <>
      <header className="app-header">
        <h1>台股 AI 預測模型系統</h1>
      </header>
      <nav className="navbar">
        <div className="nav-links">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            模型列表
          </NavLink>
          <NavLink to="/tutorial" className={({ isActive }) => (isActive ? "active" : "")}>
            股市教學
          </NavLink>
          <NavLink to="/model-tutorial" className={({ isActive }) => (isActive ? "active" : "")}>
            模型教學
          </NavLink>
          {isAdmin && (
            <>
              <NavLink to="/admin" end className={({ isActive }) => (isActive ? "active" : "")}>
                管理後台
              </NavLink>
              <NavLink to="/admin/models" className={({ isActive }) => (isActive ? "active" : "")}>
                模型管理
              </NavLink>
            </>
          )}
        </div>
        <div className="nav-user" ref={menuRef}>
          {isAuthenticated ? (
            <>
              <button className="nav-user-btn" onClick={() => setMenuOpen((open) => !open)}>
                {nickname ?? username}
                <span className={`nav-user-caret ${menuOpen ? "open" : ""}`}>▾</span>
              </button>
              {menuOpen && (
                <div className="nav-user-menu">
                  <button className="danger" onClick={handleLogout}>登出</button>
                </div>
              )}
            </>
          ) : (
            <Link to="/login" className="nav-user-btn">
              管理員登入
            </Link>
          )}
        </div>
      </nav>
      <div key={location.pathname} className="page-transition">
        <Outlet />
      </div>
    </>
  );
}
