import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AnalyticsPage from '../../src/app/analytics/page';

const mockShowToast = jest.fn();

jest.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

describe('AnalyticsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
  });

  const mockAnalytics = {
    trends: [
      { date: '2024-01-01', critical: 2, high: 3, medium: 5, low: 8 },
      { date: '2024-01-02', critical: 1, high: 2, medium: 4, low: 6 },
    ],
    comparisons: [
      { id: 'e1', target_url: 'https://example.com', findings_count: 10, critical_count: 2, high_count: 3, duration_minutes: 45, created_at: '2024-01-01' },
    ],
  };

  it('date range buttons work', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/analytics')) {
        return Promise.resolve({ ok: true, json: async () => mockAnalytics });
      }
      if (url.includes('/api/reports/scheduled')) {
        return Promise.resolve({ ok: true, json: async () => ({ reports: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AnalyticsPage />);
    await waitFor(() => {
      expect(screen.getByText('7D')).toBeInTheDocument();
      expect(screen.getByText('30D')).toBeInTheDocument();
      expect(screen.getByText('90D')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('7D'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('range=7d'), expect.anything());
    });
  });

  it('charts render with mocked Recharts', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/analytics')) {
        return Promise.resolve({ ok: true, json: async () => mockAnalytics });
      }
      if (url.includes('/api/reports/scheduled')) {
        return Promise.resolve({ ok: true, json: async () => ({ reports: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AnalyticsPage />);
    await waitFor(() => {
      expect(screen.getByTestId('recharts-responsive-container')).toBeInTheDocument();
    });
  });

  it('scheduled reports list renders', async () => {
    const reports = [
      { id: 'r1', name: 'Weekly Summary', report_type: 'summary', frequency: 'weekly', is_active: true, next_run_at: '2024-01-08', email_recipients: ['a@b.com'] },
    ];
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/analytics')) {
        return Promise.resolve({ ok: true, json: async () => mockAnalytics });
      }
      if (url.includes('/api/reports/scheduled')) {
        return Promise.resolve({ ok: true, json: async () => ({ reports }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AnalyticsPage />);
    await waitFor(() => {
      expect(screen.getByText('Weekly Summary')).toBeInTheDocument();
    });
  });

  it('create report form works', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string, init?: any) => {
      if (url.includes('/api/analytics')) {
        return Promise.resolve({ ok: true, json: async () => mockAnalytics });
      }
      if (url.includes('/api/reports/scheduled')) {
        if (init?.method === 'POST') {
          return Promise.resolve({ ok: true, json: async () => ({ id: 'new-report' }) });
        }
        return Promise.resolve({ ok: true, json: async () => ({ reports: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AnalyticsPage />);
    await waitFor(() => {
      expect(screen.getByText('New Schedule')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('New Schedule'));
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Weekly Security Summary')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText('Weekly Security Summary'), { target: { value: 'My Report' } });
    fireEvent.click(screen.getByText('Create Scheduled Report'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/reports/scheduled', expect.objectContaining({ method: 'POST' }));
    });
  });
});
