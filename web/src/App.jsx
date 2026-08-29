import { useState } from 'react'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import Login from './components/Login'
import Sidebar from './components/Sidebar'
import QueryMode from './components/QueryMode'
import ForgeMode from './components/ForgeMode'
import ReportMode from './components/ReportMode'
import Settings from './components/Settings'
import SessionHistory from './components/SessionHistory'
import AdminDashboard from './components/AdminDashboard'

function AppContent() {
  const { user, loading } = useAuth()
  const [mode, setMode] = useState('query')
  const [selectedSandbox, setSelectedSandbox] = useState(null)
  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [showAdmin, setShowAdmin] = useState(false)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen w-screen bg-slate-950">
        <div className="text-center">
          <div className="text-4xl mb-3 animate-pulse">🧠</div>
          <p className="text-slate-500 text-sm font-mono animate-pulse">Loading...</p>
        </div>
      </div>
    )
  }

  if (!user) return <Login />

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-900 text-slate-100">
      <Sidebar
        mode={mode}
        onModeChange={setMode}
        selectedSandbox={selectedSandbox}
        onSandboxSelect={setSelectedSandbox}
        onOpenSettings={() => setShowSettings(true)}
        onOpenSessions={() => setShowSessions(true)}
        onOpenAdmin={user?.role === 'admin' ? () => setShowAdmin(true) : undefined}
      />
      <main className="flex-1 overflow-hidden relative">
        {mode === 'query' ? (
          <QueryMode selectedSandbox={selectedSandbox} sessionId={currentSessionId} />
        ) : mode === 'forge' ? (
          <ForgeMode selectedSandbox={selectedSandbox} />
        ) : mode === 'report' ? (
          <ReportMode selectedSandbox={selectedSandbox} onBack={() => setMode('query')} />
        ) : null}
      </main>
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      <SessionHistory
        workspace={selectedSandbox}
        isOpen={showSessions}
        onClose={() => setShowSessions(false)}
        onLoadSession={(sid) => { setCurrentSessionId(sid); setShowSessions(false) }}
      />
      {showAdmin && <AdminDashboard onClose={() => setShowAdmin(false)} />}
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
