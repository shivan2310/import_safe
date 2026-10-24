import { Link, NavLink, Outlet } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { USE_MOCK } from "../api";
import { DemoBanner } from "./StateViews";

const navCls = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${isActive ? "bg-white/15 text-white" : "text-white/80 hover:text-white"}`;

export default function Layout() {
  return (
    <div className="min-h-screen">
      <header className="no-print bg-navy text-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2 text-lg font-bold">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
            ImportSafe
          </Link>
          <nav aria-label="Main" className="flex gap-1">
            <NavLink to="/" end className={navCls}>
              New investigation
            </NavLink>
            <NavLink to="/history" className={navCls}>
              History
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-6">
        {USE_MOCK && (
          <div className="no-print">
            <DemoBanner>
              Mock mode: results come from labelled demo fixtures in this browser, not live retrieval or
              official sources.
            </DemoBanner>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
