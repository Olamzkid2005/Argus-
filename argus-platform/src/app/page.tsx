export default function Home() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800">
      <div className="text-center px-4">
        <h1 className="text-6xl font-bold text-white mb-4">
          Argus
        </h1>
        <p className="text-xl text-slate-300 mb-8">
          AI-Powered Penetration Testing Platform
        </p>
        <div className="flex gap-4 justify-center">
          <a
            href="/dashboard"
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            Get Started
          </a>
          <a
            href="/docs"
            className="px-6 py-3 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition-colors"
          >
            Documentation
          </a>
        </div>
        <div className="mt-12 text-slate-400 text-sm">
          <p>Status: Development</p>
          <p className="mt-2">PostgreSQL ✓ | Redis ✓ | Workers Ready</p>
        </div>
      </div>
    </div>
  );
}
