import {
  BookOpen,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  GitBranch,
  LayoutDashboard,
  MapPinned,
  PlugZap,
  PanelLeftOpen,
  Route,
  ShieldCheck,
  Sparkles,
  Tags,
  Truck,
  X,
  type LucideIcon,
} from "lucide-react";

export type AppPage =
  | "dashboard"
  | "master-data"
  | "restricted-roads"
  | "tag-consistency"
  | "departure-intelligence"
  | "pairing-intelligence"
  | "affinity-intelligence"
  | "machine-learning-intelligence"
  | "prediction-assignment"
  | "phase7-optimization"
  | "manual-dispatch"
  | "route-model-alignment"
  | "amt-scheduler-connector"
  | "google-maps-integration"
  | "documentation";

type NavItem = {
  page: AppPage;
  label: string;
  icon: LucideIcon;
  phase?: number;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

const navGroups: NavGroup[] = [
  {
    label: "Overview",
    items: [{ page: "dashboard", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Data Foundation",
    items: [
      { page: "master-data", label: "Master Data", icon: Database },
      { page: "restricted-roads", label: "Restricted Roads", icon: MapPinned },
      { page: "tag-consistency", label: "Tag Consistency", icon: ShieldCheck },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { page: "departure-intelligence", label: "Departure Time", icon: Clock3, phase: 2 },
      { page: "pairing-intelligence", label: "SPBU Pairing", icon: GitBranch, phase: 3 },
      { page: "affinity-intelligence", label: "SPBU–MT Affinity", icon: Tags, phase: 4 },
      { page: "machine-learning-intelligence", label: "Machine Learning", icon: BrainCircuit, phase: 5 },
    ],
  },
  {
    label: "Planning",
    items: [
      { page: "prediction-assignment", label: "Prediction & Assignment", icon: Sparkles, phase: 6 },
      { page: "phase7-optimization", label: "Dynamic VRP & Bay", icon: Truck, phase: 7 },
      { page: "manual-dispatch", label: "Manual Dispatching", icon: Route, phase: 8 },
    ],
  },
  {
    label: "Evaluation",
    items: [
      { page: "route-model-alignment", label: "Route–Model Alignment", icon: GitBranch, phase: 9 },
    ],
  },
  {
    label: "Integration",
    items: [
      { page: "amt-scheduler-connector", label: "AMT Scheduler Connector", icon: PlugZap, phase: 10 },
    ],
  },
  {
    label: "Settings",
    items: [
      { page: "google-maps-integration", label: "Google Maps Settings", icon: MapPinned },
    ],
  },
  {
    label: "Support",
    items: [
      { page: "documentation", label: "Documentation", icon: BookOpen },
    ],
  },
];

type AppSidebarProps = {
  currentPage: AppPage;
  collapsed: boolean;
  mobileOpen: boolean;
  onNavigate: (page: AppPage) => void;
  onToggleCollapsed: () => void;
  onCloseMobile: () => void;
};

export function AppSidebar({
  currentPage,
  collapsed,
  mobileOpen,
  onNavigate,
  onToggleCollapsed,
  onCloseMobile,
}: AppSidebarProps) {
  return (
    <>
      <button
        type="button"
        className={`sidebar-scrim ${mobileOpen ? "is-visible" : ""}`}
        aria-label="Close navigation menu"
        onClick={onCloseMobile}
      />

      <aside className={`app-sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}>
        <div className="sidebar-brand-row">
          <button
            type="button"
            className="petrofin-brand"
            onClick={() => onNavigate("dashboard")}
            aria-label="Elnusa Petrofin dashboard"
            title="Elnusa Petrofin"
          >
            <span className="petrofin-mark" aria-hidden="true">
              <span>P</span>
            </span>
            <span className="petrofin-wordmark">
              <span>elnusa</span>
              <strong>petrofin</strong>
            </span>
          </button>

          <button type="button" className="sidebar-mobile-close" onClick={onCloseMobile} aria-label="Close navigation menu">
            <X size={19} />
          </button>

          <button
            type="button"
            className="sidebar-collapse-top"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        <nav className="sidebar-navigation" aria-label="Main navigation">
          {navGroups.map((group) => (
            <div className="sidebar-group" key={group.label}>
              <div className="sidebar-group-label">{group.label}</div>
              <div className="sidebar-group-items">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = currentPage === item.page;
                  return (
                    <button
                      type="button"
                      key={item.page}
                      className={`sidebar-nav-item ${active ? "is-active" : ""}`}
                      onClick={() => onNavigate(item.page)}
                      aria-current={active ? "page" : undefined}
                      title={collapsed ? item.label : undefined}
                    >
                      {item.phase ? (
                        <span className="sidebar-phase" aria-hidden="true">{item.phase}</span>
                      ) : (
                        <span className="sidebar-icon" aria-hidden="true"><Icon size={19} strokeWidth={1.9} /></span>
                      )}
                      <span className="sidebar-item-label">{item.label}</span>
                      {active && <ChevronRight className="sidebar-active-caret" size={16} aria-hidden="true" />}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className="sidebar-footer-button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen size={19} /> : <ChevronLeft size={19} />}
            <span>{collapsed ? "" : "Collapse"}</span>
          </button>
          {!collapsed && (
            <div className="sidebar-product-note">
              <Route size={14} />
              Dispatch Intelligence
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
