import { Navigate, Route, Routes, useOutletContext } from "react-router-dom";

import { AppShell, type AppOutletContext } from "./AppShell";
import { copy } from "./copy";
import {
  ProtectedRoute,
  PublicOnlyRoute,
  AdminRoute,
} from "../features/auth/AuthGate";
import { LoginPage } from "../routes/auth/LoginPage";
import { ForgotPasswordPage } from "../routes/auth/ForgotPasswordPage";
import { AuthCallbackPage } from "../routes/auth/AuthCallbackPage";
import { AdminUsersPage } from "../routes/admin/users/AdminUsersPage";
import { AdminProvidersPage } from "../routes/admin/providers/AdminProvidersPage";
import { AssignmentsPage } from "../features/assignments/AssignmentsPage";
import { EditAssignmentPage } from "../features/assignments/EditAssignmentPage";
import { NewAssignmentPage } from "../features/assignments/NewAssignmentPage";
import { RubricPage } from "../features/rubrics/RubricPage";
import { SubmissionsPage } from "../features/submissions/SubmissionsPage";
import { GradingJobsPage } from "../features/jobs/GradingJobsPage";
import { ReviewWorkbenchPage } from "../features/reviews/ReviewWorkbenchPage";
import { ExportsPage } from "../features/exports/ExportsPage";

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
      <Route
        path="/login"
        element={
          <PublicOnlyRoute>
            <LoginPage />
          </PublicOnlyRoute>
        }
      />
      <Route
        path="/forgot-password"
        element={
          <PublicOnlyRoute>
            <ForgotPasswordPage />
          </PublicOnlyRoute>
        }
      />
      <Route path="/auth/callback" element={<AuthCallbackPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/assignments" element={<AssignmentsPage />} />
        <Route path="/assignments/new" element={<NewAssignmentPage />} />
        <Route path="/assignments/:assignmentId/edit" element={<EditAssignmentPage />} />
        <Route path="/assignments/:assignmentId/rubric" element={<RubricPage />} />
        <Route path="/assignments/:assignmentId/submissions" element={<SubmissionsPage />} />
        <Route path="/grading-jobs" element={<GradingJobsPage />} />
        <Route
          path="/grading-jobs/:jobId/reviews/:itemId"
          element={<ReviewWorkbenchPage />}
        />
        <Route path="/exports" element={<ExportsPage />} />
        <Route
          path="/admin/users"
          element={
            <AdminRoute>
              <AdminUsersPage />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/providers"
          element={
            <AdminRoute>
              <AdminProvidersPage />
            </AdminRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
