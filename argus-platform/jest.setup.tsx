import '@testing-library/jest-dom';
import React from 'react';

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    prefetch: jest.fn(),
    pathname: '/',
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

// Mock next-auth
jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        email: 'test@example.com',
        name: 'Test User',
      },
    },
    status: 'authenticated',
  }),
  signIn: jest.fn(),
  signOut: jest.fn(),
  getSession: jest.fn(() => Promise.resolve({
    user: {
      email: 'test@example.com',
      name: 'Test User',
    },
  })),
}));

// Mock next-themes
jest.mock('next-themes', () => ({
  useTheme: () => ({
    theme: 'light',
    setTheme: jest.fn(),
    resolvedTheme: 'light',
  }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock framer-motion to avoid animation issues in tests
jest.mock('framer-motion', () => ({
  motion: {
    div: React.forwardRef(({ children, ...props }: any, ref: any) => <div ref={ref} {...props}>{children}</div>),
    span: ({ children, ...props }: any) => <span {...props}>{children}</span>,
    article: ({ children, ...props }: any) => <article {...props}>{children}</article>,
    section: ({ children, ...props }: any) => <section {...props}>{children}</section>,
    nav: ({ children, ...props }: any) => <nav {...props}>{children}</nav>,
    footer: ({ children, ...props }: any) => <footer {...props}>{children}</footer>,
    button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    input: ({ children, ...props }: any) => <input {...props} />,
    select: ({ children, ...props }: any) => <select {...props}>{children}</select>,
    textarea: ({ children, ...props }: any) => <textarea {...props}>{children}</textarea>,
    form: ({ children, ...props }: any) => <form {...props}>{children}</form>,
    ul: ({ children, ...props }: any) => <ul {...props}>{children}</ul>,
    li: ({ children, ...props }: any) => <li {...props}>{children}</li>,
    ol: ({ children, ...props }: any) => <ol {...props}>{children}</ol>,
    a: ({ children, ...props }: any) => <a {...props}>{children}</a>,
    img: ({ children, ...props }: any) => <img {...props} />,
    svg: ({ children, ...props }: any) => <svg {...props}>{children}</svg>,
    path: ({ children, ...props }: any) => <path {...props} />,
    circle: ({ children, ...props }: any) => <circle {...props} />,
    line: ({ children, ...props }: any) => <line {...props} />,
    polyline: ({ children, ...props }: any) => <polyline {...props} />,
    polygon: ({ children, ...props }: any) => <polygon {...props} />,
    rect: ({ children, ...props }: any) => <rect {...props} />,
    g: ({ children, ...props }: any) => <g {...props}>{children}</g>,
    text: ({ children, ...props }: any) => <text {...props}>{children}</text>,
    tspan: ({ children, ...props }: any) => <tspan {...props}>{children}</tspan>,
    defs: ({ children, ...props }: any) => <defs {...props}>{children}</defs>,
    clipPath: ({ children, ...props }: any) => <clipPath {...props}>{children}</clipPath>,
    linearGradient: ({ children, ...props }: any) => <linearGradient {...props}>{children}</linearGradient>,
    stop: ({ children, ...props }: any) => <stop {...props} />,
    filter: ({ children, ...props }: any) => <filter {...props}>{children}</filter>,
    feGaussianBlur: ({ children, ...props }: any) => <feGaussianBlur {...props} />,
    feOffset: ({ children, ...props }: any) => <feOffset {...props} />,
    feFlood: ({ children, ...props }: any) => <feFlood {...props} />,
    feComposite: ({ children, ...props }: any) => <feComposite {...props} />,
    feBlend: ({ children, ...props }: any) => <feBlend {...props} />,
    foreignObject: ({ children, ...props }: any) => <foreignObject {...props}>{children}</foreignObject>,
    table: ({ children, ...props }: any) => <table {...props}>{children}</table>,
    thead: ({ children, ...props }: any) => <thead {...props}>{children}</thead>,
    tbody: ({ children, ...props }: any) => <tbody {...props}>{children}</tbody>,
    tr: ({ children, ...props }: any) => <tr {...props}>{children}</tr>,
    th: ({ children, ...props }: any) => <th {...props}>{children}</th>,
    td: ({ children, ...props }: any) => <td {...props}>{children}</td>,
    h1: ({ children, ...props }: any) => <h1 {...props}>{children}</h1>,
    h2: ({ children, ...props }: any) => <h2 {...props}>{children}</h2>,
    h3: ({ children, ...props }: any) => <h3 {...props}>{children}</h3>,
    h4: ({ children, ...props }: any) => <h4 {...props}>{children}</h4>,
    h5: ({ children, ...props }: any) => <h5 {...props}>{children}</h5>,
    h6: ({ children, ...props }: any) => <h6 {...props}>{children}</h6>,
    p: ({ children, ...props }: any) => <p {...props}>{children}</p>,
    label: ({ children, ...props }: any) => <label {...props}>{children}</label>,
    strong: ({ children, ...props }: any) => <strong {...props}>{children}</strong>,
    em: ({ children, ...props }: any) => <em {...props}>{children}</em>,
    small: ({ children, ...props }: any) => <small {...props}>{children}</small>,
    sub: ({ children, ...props }: any) => <sub {...props}>{children}</sub>,
    sup: ({ children, ...props }: any) => <sup {...props}>{children}</sup>,
    br: ({ children, ...props }: any) => <br {...props} />,
    hr: ({ children, ...props }: any) => <hr {...props} />,
    wbr: ({ children, ...props }: any) => <wbr {...props} />,
    mark: ({ children, ...props }: any) => <mark {...props}>{children}</mark>,
    del: ({ children, ...props }: any) => <del {...props}>{children}</del>,
    ins: ({ children, ...props }: any) => <ins {...props}>{children}</ins>,
    b: ({ children, ...props }: any) => <b {...props}>{children}</b>,
    i: ({ children, ...props }: any) => <i {...props}>{children}</i>,
    u: ({ children, ...props }: any) => <u {...props}>{children}</u>,
    s: ({ children, ...props }: any) => <s {...props}>{children}</s>,
    code: ({ children, ...props }: any) => <code {...props}>{children}</code>,
    pre: ({ children, ...props }: any) => <pre {...props}>{children}</pre>,
    kbd: ({ children, ...props }: any) => <kbd {...props}>{children}</kbd>,
    blockquote: ({ children, ...props }: any) => <blockquote {...props}>{children}</blockquote>,
    cite: ({ children, ...props }: any) => <cite {...props}>{children}</cite>,
    q: ({ children, ...props }: any) => <q {...props}>{children}</q>,
    abbr: ({ children, ...props }: any) => <abbr {...props}>{children}</abbr>,
    dfn: ({ children, ...props }: any) => <dfn {...props}>{children}</dfn>,
    time: ({ children, ...props }: any) => <time {...props}>{children}</time>,
    var: ({ children, ...props }: any) => <var {...props}>{children}</var>,
    samp: ({ children, ...props }: any) => <samp {...props}>{children}</samp>,
    address: ({ children, ...props }: any) => <address {...props}>{children}</address>,
    dialog: ({ children, ...props }: any) => <dialog {...props}>{children}</dialog>,
    details: ({ children, ...props }: any) => <details {...props}>{children}</details>,
    summary: ({ children, ...props }: any) => <summary {...props}>{children}</summary>,
    fieldset: ({ children, ...props }: any) => <fieldset {...props}>{children}</fieldset>,
    legend: ({ children, ...props }: any) => <legend {...props}>{children}</legend>,
    datalist: ({ children, ...props }: any) => <datalist {...props}>{children}</datalist>,
    optgroup: ({ children, ...props }: any) => <optgroup {...props}>{children}</optgroup>,
    option: ({ children, ...props }: any) => <option {...props}>{children}</option>,
    progress: ({ children, ...props }: any) => <progress {...props}>{children}</progress>,
    meter: ({ children, ...props }: any) => <meter {...props}>{children}</meter>,
    output: ({ children, ...props }: any) => <output {...props}>{children}</output>,
    canvas: ({ children, ...props }: any) => <canvas {...props}>{children}</canvas>,
    iframe: ({ children, ...props }: any) => <iframe {...props}>{children}</iframe>,
    embed: ({ children, ...props }: any) => <embed {...props} />,
    object: ({ children, ...props }: any) => <object {...props}>{children}</object>,
    param: ({ children, ...props }: any) => <param {...props} />,
    source: ({ children, ...props }: any) => <source {...props} />,
    track: ({ children, ...props }: any) => <track {...props} />,
    area: ({ children, ...props }: any) => <area {...props} />,
    map: ({ children, ...props }: any) => <map {...props}>{children}</map>,

  },
  AnimatePresence: ({ children }: any) => <>{children}</>,
  useScroll: () => ({ scrollYProgress: { get: () => 0 } }),
  useTransform: () => ({ get: () => 0 }),
  useReducedMotion: () => false,
  useInView: () => true,
  useMotionValue: (val: any) => ({ get: () => val, set: jest.fn() }),
  useSpring: (val: any) => ({ get: () => val, on: jest.fn(() => jest.fn()) }),
  useMotionTemplate: () => "",
  motionValue: (val: any) => ({ get: () => val, set: jest.fn() }),
}));

// Mock recharts
jest.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="recharts-responsive-container">{children}</div>,
  BarChart: ({ children }: any) => <div data-testid="recharts-bar-chart">{children}</div>,
  Bar: () => <div data-testid="recharts-bar" />,
  XAxis: () => <div data-testid="recharts-x-axis" />,
  YAxis: () => <div data-testid="recharts-y-axis" />,
  CartesianGrid: () => <div data-testid="recharts-cartesian-grid" />,
  Tooltip: () => <div data-testid="recharts-tooltip" />,
  AreaChart: ({ children }: any) => <div data-testid="recharts-area-chart">{children}</div>,
  Area: () => <div data-testid="recharts-area" />,
  LineChart: ({ children }: any) => <div data-testid="recharts-line-chart">{children}</div>,
  Line: () => <div data-testid="recharts-line" />,
  PieChart: ({ children }: any) => <div data-testid="recharts-pie-chart">{children}</div>,
  Pie: () => <div data-testid="recharts-pie" />,
  Cell: () => <div data-testid="recharts-cell" />,
  Legend: () => <div data-testid="recharts-legend" />,
  ReferenceLine: () => <div data-testid="recharts-reference-line" />,
  Brush: () => <div data-testid="recharts-brush" />,
  ComposedChart: ({ children }: any) => <div data-testid="recharts-composed-chart">{children}</div>,
  Scatter: () => <div data-testid="recharts-scatter" />,
  ScatterChart: ({ children }: any) => <div data-testid="recharts-scatter-chart">{children}</div>,
  RadarChart: ({ children }: any) => <div data-testid="recharts-radar-chart">{children}</div>,
  Radar: () => <div data-testid="recharts-radar" />,
  PolarGrid: () => <div data-testid="recharts-polar-grid" />,
  PolarAngleAxis: () => <div data-testid="recharts-polar-angle-axis" />,
  PolarRadiusAxis: () => <div data-testid="recharts-polar-radius-axis" />,
  RadialBarChart: ({ children }: any) => <div data-testid="recharts-radial-bar-chart">{children}</div>,
  RadialBar: () => <div data-testid="recharts-radial-bar" />,
  Treemap: () => <div data-testid="recharts-treemap" />,
  Sankey: () => <div data-testid="recharts-sankey" />,
  FunnelChart: ({ children }: any) => <div data-testid="recharts-funnel-chart">{children}</div>,
  Funnel: () => <div data-testid="recharts-funnel" />,
  LabelList: () => <div data-testid="recharts-label-list" />,
  ErrorBar: () => <div data-testid="recharts-error-bar" />,
}));

// Mock useToast
jest.mock('@/components/ui/Toast', () => {
  const showToast = jest.fn();
  return {
    useToast: () => ({ showToast }),
    ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  };
});

// Mock @/lib/use-engagement-events
jest.mock('@/lib/use-engagement-events', () => ({
  useEngagementEvents: () => ({
    events: [],
    currentState: null,
    isConnected: false,
    error: null,
    reconnect: jest.fn(),
    clearEvents: jest.fn(),
  }),
  useEngagementEventType: () => ({
    events: [],
    currentState: null,
    isConnected: false,
    error: null,
    reconnect: jest.fn(),
    clearEvents: jest.fn(),
  }),
}));

// Mock @/lib/use-scanner-activities
jest.mock('@/lib/use-scanner-activities', () => ({
  useScannerActivities: () => ({
    activities: [],
    isLoading: false,
    error: null,
    refetch: jest.fn(),
  }),
}));

// Mock @/components/ui-custom/AIStatus
jest.mock('@/components/ui-custom/AIStatus', () => ({
  AIStatusIndicator: () => <div data-testid="ai-status-indicator">AI Status</div>,
  AIStatusBadge: () => <div data-testid="ai-status-badge">AI</div>,
}));

// Mock @/components/ui-custom/AttackPathGraph
jest.mock('@/components/ui-custom/AttackPathGraph', () => ({
  __esModule: true,
  default: () => <div data-testid="attack-path-graph">Attack Path Graph</div>,
}));

// Mock @/components/ui-custom/ExecutionTimeline
jest.mock('@/components/ui-custom/ExecutionTimeline', () => ({
  __esModule: true,
  default: () => <div data-testid="execution-timeline">Execution Timeline</div>,
}));

// Mock @/components/ui-custom/ToolPerformanceMetrics
jest.mock('@/components/ui-custom/ToolPerformanceMetrics', () => ({
  __esModule: true,
  default: () => <div data-testid="tool-performance-metrics">Tool Performance Metrics</div>,
}));

// Mock @/components/ui-custom/MarkdownRenderer
jest.mock('@/components/ui-custom/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: any) => <div data-testid="markdown-renderer">{content}</div>,
}));

// Mock @/components/ui-custom/ScannerActivityPanel
jest.mock('@/components/ui-custom/ScannerActivityPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="scanner-activity-panel">Scanner Activity Panel</div>,
}));

// Mock @/components/ui-custom/ScanModeHelp
jest.mock('@/components/ui-custom/ScanModeHelp', () => ({
  __esModule: true,
  default: ({ trigger }: any) => <span data-testid="scan-mode-help">{trigger}</span>,
}));

// Mock @/components/ui-custom/SkeletonLoader
jest.mock('@/components/ui-custom/SkeletonLoader', () => ({
  __esModule: true,
  default: () => <div data-testid="skeleton-loader">Loading...</div>,
}));

// Mock @/components/effects/MatrixDataRain
jest.mock('@/components/effects/MatrixDataRain', () => ({
  __esModule: true,
  default: () => <div data-testid="matrix-data-rain">Matrix Data Rain</div>,
}));

// Mock @/components/effects/SurveillanceEye
jest.mock('@/components/effects/SurveillanceEye', () => ({
  __esModule: true,
  default: () => <div data-testid="surveillance-eye">Surveillance Eye</div>,
}));

// Mock @/components/effects/ScannerReveal
jest.mock('@/components/effects/ScannerReveal', () => ({
  __esModule: true,
  default: () => <div data-testid="scanner-reveal">Scanner Reveal</div>,
}));

// Mock uuid
jest.mock('uuid', () => ({
  v4: jest.fn(() => 'mock-uuid'),
}));

// Mock @/lib/db for API route tests
jest.mock('@/lib/db', () => ({
  pool: {
    on: jest.fn(),
    connect: jest.fn(() => Promise.resolve({
      query: jest.fn(() => Promise.resolve({ rows: [], rowCount: 0 })),
      release: jest.fn(),
    })),
    query: jest.fn(() => Promise.resolve({ rows: [], rowCount: 0 })),
    totalCount: 0,
    idleCount: 0,
    waitingCount: 0,
  },
  query: jest.fn(() => Promise.resolve({ rows: [], rowCount: 0 })),
  withClient: jest.fn((cb) => cb({ query: jest.fn(), release: jest.fn() })),
  getPoolStats: jest.fn(() => ({ totalCount: 0, idleCount: 0, waitingCount: 0, maxConnections: 20, minConnections: 2, queryMetrics: {} })),
  setTenantContext: jest.fn(),
  resetTenantContext: jest.fn(),
}));

// Minimal Request/Response polyfills for Next.js API route tests
class MockRequest {
  private _url: string;
  method: string;
  headers: Headers;
  constructor(input: string | Request, init?: RequestInit) {
    this._url = typeof input === 'string' ? input : (input as any).url;
    this.method = init?.method || 'GET';
    this.headers = new Headers(init?.headers);
  }
  get url() { return this._url; }
}
class MockResponse {
  status: number;
  statusText: string;
  headers: Headers;
  body: any;
  constructor(body?: BodyInit | null, init?: ResponseInit) {
    this.body = body;
    this.status = init?.status || 200;
    this.statusText = init?.statusText || '';
    this.headers = new Headers(init?.headers);
  }
  json() { return Promise.resolve(this.body ? JSON.parse(this.body as string) : null); }
  text() { return Promise.resolve(String(this.body)); }
}
if (typeof Request === 'undefined') {
  global.Request = MockRequest as any;
}
if (typeof Response === 'undefined') {
  global.Response = MockResponse as any;
}

// Mock next/server for API route tests
jest.mock('next/server', () => ({
  NextResponse: {
    json: (body?: any, init?: ResponseInit) => {
      const response = new Response(body ? JSON.stringify(body) : null, init);
      // @ts-ignore
      response.json = async () => body;
      return response;
    },
  },
  NextRequest: class NextRequest extends (global.Request || class { constructor(public input: any, public init?: any) {} }) {
    nextUrl = new URL('http://localhost:3000');
  },
}));

// window.location.origin defaults to 'http://localhost' in jsdom, sufficient for polling tests

// Global fetch mock
global.fetch = jest.fn();

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

// Mock sessionStorage
const sessionStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
Object.defineProperty(window, 'sessionStorage', {
  value: sessionStorageMock,
});

// Mock navigator.clipboard
Object.defineProperty(navigator, 'clipboard', {
  value: {
    writeText: jest.fn(() => Promise.resolve()),
  },
});

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
});

// Mock IntersectionObserver
class MockIntersectionObserver {
  observe = jest.fn();
  disconnect = jest.fn();
  unobserve = jest.fn();
}
Object.defineProperty(window, 'IntersectionObserver', {
  writable: true,
  value: MockIntersectionObserver,
});

// Mock ResizeObserver
class MockResizeObserver {
  observe = jest.fn();
  disconnect = jest.fn();
  unobserve = jest.fn();
}
Object.defineProperty(window, 'ResizeObserver', {
  writable: true,
  value: MockResizeObserver,
});
