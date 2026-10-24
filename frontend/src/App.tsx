import { Link, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { EmptyState } from "./components/StateViews";
import NewInvestigationPage from "./pages/NewInvestigationPage";
import InvestigationPage from "./pages/InvestigationPage";
import ReportPage from "./pages/ReportPage";
import HistoryPage from "./pages/HistoryPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<NewInvestigationPage />} />
        <Route path="investigations/:id" element={<InvestigationPage />} />
        <Route path="investigations/:id/report" element={<ReportPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route
          path="*"
          element={
            <EmptyState title="Page not found">
              <Link to="/" className="btn-primary">
                Go home
              </Link>
            </EmptyState>
          }
        />
      </Route>
    </Routes>
  );
}
