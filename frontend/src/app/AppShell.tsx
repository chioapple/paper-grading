import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../features/auth/AuthContext";
import { copy, type Language } from "./copy";
import { Icon } from "./icons";

export type AppOutletContext = {
  language: Language;
};

export function AppShell() {
  const { account, signOut } = useAuth();
  const navigate = useNavigate();
  const [language, setLanguage] = useState<Language>("zh");
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isAccountOpen, setIsAccountOpen] = useState(false);
  const text = copy[language];

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  const navigation = [
    { to: "/assignments", label: text.assignments, icon: "document" as const },
    { to: "/grading-jobs", label: text.gradingJobs, icon: "clipboard" as const },
    { to: "/exports", label: text.exports, icon: "download" as const },
    ...(account?.role === "admin"
      ? [
          { to: "/admin/users", label: text.teacherAccounts, icon: "accounts" as const },
          { to: "/admin/providers", label: text.modelProviders, icon: "settings" as const },
        ]
      : []),
  ];

  async function handleSignOut() {
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className={`app-shell${isCollapsed ? " app-shell--collapsed" : ""}`}>
      <aside className="sidebar" aria-label={text.mainNavigation}>
        <div className="brand">
          <Icon className="brand__icon" name="brand" />
          <span className="brand__name">Paper Grading</span>
        </div>

        <nav className="sidebar__nav">
          {navigation.map((item) => (
            <NavLink
              className={({ isActive }) =>
                `nav-item${isActive ? " nav-item--active" : ""}`
              }
              key={item.to}
              to={item.to}
              title={isCollapsed ? item.label : undefined}
            >
              <Icon className="nav-item__icon" name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <button
          className="collapse-button"
          type="button"
          onClick={() => setIsCollapsed((value) => !value)}
          aria-expanded={!isCollapsed}
          aria-label={isCollapsed ? text.expand : text.collapse}
        >
          <span className="collapse-button__icon">
            <Icon name="chevronLeft" />
          </span>
          <span>{isCollapsed ? text.expand : text.collapse}</span>
        </button>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <button
            className="utility-button"
            type="button"
            onClick={() => setLanguage((value) => (value === "zh" ? "en" : "zh"))}
            aria-label={language === "zh" ? "Switch to English" : "切换为中文"}
          >
            <Icon name="globe" />
            <span>中 / EN</span>
            <Icon className="utility-button__chevron" name="chevronDown" />
          </button>
          <div className="account-menu">
            <button
              className="account-button"
              type="button"
              aria-controls="account-popover"
              aria-expanded={isAccountOpen}
              onClick={() => setIsAccountOpen((value) => !value)}
            >
              <span className="account-button__icon">
                <Icon name="user" />
              </span>
              <span>{account?.display_name ?? text.teacher}</span>
              <Icon className="account-button__chevron" name="chevronDown" />
            </button>
            {isAccountOpen ? (
              <section className="account-popover" id="account-popover" aria-live="polite">
                <h2>{text.accountTitle}</h2>
                <strong>
                  {account?.role === "admin" ? text.adminRole : text.teacherRole}
                </strong>
                <p>{account?.email}</p>
                <button className="account-popover__logout" onClick={handleSignOut} type="button">
                  {text.signOut}
                </button>
              </section>
            ) : null}
          </div>
        </header>

        <Outlet context={{ language } satisfies AppOutletContext} />
      </main>
    </div>
  );
}
