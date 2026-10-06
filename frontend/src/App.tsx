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

const modulePages = navItems.filter((item) => item.path !== '/dashboard')

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
