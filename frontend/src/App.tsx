import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import HomePage from "./pages/HomePage";
import LeaderboardPage from "./pages/LeaderboardPage";
import LoginPage from "./pages/LoginPage";
import PositionPage from "./pages/PositionPage";
import RegisterPage from "./pages/RegisterPage";
import SearchPage from "./pages/SearchPage";
import StrategyPage from "./pages/StrategyPage";
import TradeHistoryPage from "./pages/TradeHistoryPage";
import TradePage from "./pages/TradePage";
import TutorialPage from "./pages/TutorialPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/trade" element={<TradePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/history" element={<TradeHistoryPage />} />
            <Route path="/positions" element={<PositionPage />} />
            <Route path="/strategy" element={<StrategyPage />} />
            <Route path="/leaderboard" element={<LeaderboardPage />} />
            <Route path="/tutorial" element={<TutorialPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
