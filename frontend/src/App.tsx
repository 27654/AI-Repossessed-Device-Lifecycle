import type { ReactNode } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import AuthProvider from './auth/AuthProvider'
import RequireAuth from './auth/RequireAuth'
import { navItems } from './config/navigation'
import AppLayout from './layouts/AppLayout'
import AccountPage from './pages/AccountPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import MfaVerifyPage from './pages/MfaVerifyPage'
import NotFoundPage from './pages/NotFoundPage'
import PlaceholderPage from './pages/PlaceholderPage'
import DeviceDetailPage from './pages/devices/DeviceDetailPage'
import DeviceFormPage from './pages/devices/DeviceFormPage'
import DeviceListPage from './pages/devices/DeviceListPage'
import AIRecommendationListPage from './pages/assessments/AIRecommendationListPage'
import AssessmentListPage from './pages/assessments/AssessmentListPage'
import DispositionListPage from './pages/dispositions/DispositionListPage'
import RecoveryListPage from './pages/recovery/RecoveryListPage'
import RefurbishmentListPage from './pages/refurbishment/RefurbishmentListPage'
import { Perm } from './config/permissions'

// Modules not built yet show a placeholder.
const IMPLEMENTED = [
  '/dashboard',
  '/devices',
  '/recovery',
  '/assessments',
  '/ai-recommendations',
  '/refurbishments',
  '/dispositions',
]
const modulePages = navItems.filter((item) => !IMPLEMENTED.includes(item.path))

const guarded = (permission: string, element: ReactNode) => (
  <RequireAuth permission={permission}>{element}</RequireAuth>
)

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/login/mfa', element: <MfaVerifyPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'account', element: <AccountPage /> },
      { path: 'devices', element: guarded(Perm.DEVICE_VIEW, <DeviceListPage />) },
      { path: 'devices/new', element: guarded(Perm.DEVICE_CREATE, <DeviceFormPage />) },
      { path: 'devices/:id', element: guarded(Perm.DEVICE_VIEW, <DeviceDetailPage />) },
      { path: 'devices/:id/edit', element: guarded(Perm.DEVICE_UPDATE, <DeviceFormPage />) },
      { path: 'recovery', element: guarded(Perm.RECOVERY_MANAGE, <RecoveryListPage />) },
      { path: 'assessments', element: guarded(Perm.ASSESSMENT_CREATE, <AssessmentListPage />) },
      { path: 'ai-recommendations', element: guarded(Perm.AI_VIEW, <AIRecommendationListPage />) },
      { path: 'refurbishments', element: guarded(Perm.REFURBISHMENT_MANAGE, <RefurbishmentListPage />) },
      { path: 'dispositions', element: guarded(Perm.DISPOSITION_CREATE, <DispositionListPage />) },
      ...modulePages.map((item) => ({
        path: item.path.slice(1),
        element: (
          <RequireAuth permission={item.permission}>
            <PlaceholderPage title={item.label} />
          </RequireAuth>
        ),
      })),
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
