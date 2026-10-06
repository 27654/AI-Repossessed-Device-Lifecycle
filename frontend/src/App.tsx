import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { navItems } from './config/navigation'
import AppLayout from './layouts/AppLayout'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import NotFoundPage from './pages/NotFoundPage'
import PlaceholderPage from './pages/PlaceholderPage'

const modulePages = navItems.filter((item) => item.path !== '/dashboard')

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <DashboardPage /> },
      ...modulePages.map((item) => ({
        path: item.path.slice(1),
        element: <PlaceholderPage title={item.label} />,
      })),
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
