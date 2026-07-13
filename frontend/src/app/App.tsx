import { useState } from "react";
import { Navigate, Route, Routes, useOutletContext } from "react-router-dom";

import { AppShell, type AppOutletContext } from "./AppShell";
import { copy } from "./copy";
import { Icon } from "./icons";

function AssignmentsPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const text = copy[language];

  return (
    <div className="page assignments-page">
      <section className="page-header">
        <h1>{text.welcome}</h1>
        <p>{text.intro}</p>
        <button
          className="primary-button"
          type="button"
          onClick={() => setIsCreateOpen(true)}
        >
          <Icon name="plus" />
          <span>{text.createAssignment}</span>
        </button>
      </section>

      {isCreateOpen ? (
        <section className="create-notice" aria-live="polite">
          <div>
            <h2>{text.createTitle}</h2>
            <p>{text.createBody}</p>
          </div>
          <button type="button" onClick={() => setIsCreateOpen(false)}>
            {text.close}
          </button>
        </section>
      ) : null}

      <section className="empty-state">
        <div className="empty-state__icon">
          <Icon name="inbox" />
        </div>
        <h2>{text.emptyTitle}</h2>
        <p>{text.emptyBody}</p>
        <button
          className="primary-button"
          type="button"
          onClick={() => setIsCreateOpen(true)}
        >
          <Icon name="plus" />
          <span>{text.createAssignment}</span>
        </button>
      </section>
    </div>
  );
}

function PlannedPage({ area }: { area: "jobs" | "exports" }) {
  const { language } = useOutletContext<AppOutletContext>();
  const text = copy[language];
  const isJobs = area === "jobs";

  return (
    <div className="page planned-page">
      <h1>{isJobs ? text.jobsTitle : text.exportsTitle}</h1>
      <p>{isJobs ? text.jobsBody : text.exportsBody}</p>
    </div>
  );
}

function NotFoundPage() {
  const { language } = useOutletContext<AppOutletContext>();
  return (
    <div className="page planned-page">
      <h1>{copy[language].notFoundTitle}</h1>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate replace to="/assignments" />} />
      <Route element={<AppShell />}>
        <Route path="/assignments" element={<AssignmentsPage />} />
        <Route path="/grading-jobs" element={<PlannedPage area="jobs" />} />
        <Route path="/exports" element={<PlannedPage area="exports" />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
