import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import AdminModelsPage from "./pages/AdminModelsPage";
import AdminPage from "./pages/AdminPage";
import LoginPage from "./pages/LoginPage";
import PlaceholderHomePage from "./pages/PlaceholderHomePage";
import TutorialPage from "./pages/TutorialPage";

// 這個系統轉型成公開的 AI 預測模型儀表板：一般使用者不再註冊/登入，
// 只有 admin 需要登入來訓練/管理模型。舊的一般使用者頁面（手動交易、
// 自選股、排行榜、個人策略）程式碼還在，只是不再掛路由對外開放。
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<PlaceholderHomePage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/admin/models" element={<AdminModelsPage />} />
            <Route path="/tutorial" element={<TutorialPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
