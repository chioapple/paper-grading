import { useEffect, useState, type ReactNode } from "react";

import { Icon } from "../../app/icons";
import type { Language } from "../../app/copy";

export function AuthLayout({
  children,
}: {
  children: (language: Language) => ReactNode;
}) {
  const [language, setLanguage] = useState<Language>("zh");

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  return (
    <div className="auth-layout">
      <header className="auth-header">
        <div className="brand auth-brand">
          <Icon className="brand__icon" name="brand" />
          <span className="brand__name">Paper Grading</span>
        </div>
        <button
          aria-label={language === "zh" ? "Switch to English" : "切换为中文"}
          className="auth-language"
          onClick={() => setLanguage((value) => (value === "zh" ? "en" : "zh"))}
          type="button"
        >
          <Icon name="globe" />
          <span>中 / EN</span>
          <Icon name="chevronDown" />
        </button>
      </header>
      {children(language)}
    </div>
  );
}
