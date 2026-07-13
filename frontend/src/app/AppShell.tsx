import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { copy, type Language } from "./copy";
import { Icon } from "./icons";

export type AppOutletContext = {
  language: Language;
};

export function AppShell() {
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
  ];

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
              <span>{text.teacher}</span>
              <Icon className="account-button__chevron" name="chevronDown" />
            </button>
            {isAccountOpen ? (
              <section className="account-popover" id="account-popover" aria-live="polite">
                <h2>{text.accountTitle}</h2>
                <strong>{text.accountRole}</strong>
                <p>{text.accountBody}</p>
              </section>
            ) : null}
          </div>
        </header>

        <Outlet context={{ language } satisfies AppOutletContext} />
      </main>
    </div>
  );
}
