import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ReportsPage from '../../src/app/reports/page';

const mockPush = jest.fn();
const mockShowToast = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

describe('ReportsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
  });

  const mockReports = [
    { id: 'r1', name: 'Engagement Report', type: 'engagement', status: 'ready', created_at: '2024-01-01', format: 'pdf' },
    { id: 'r2', name: 'Finding Report', type: 'finding', status: 'generating', created_at: '2024-01-02', format: 'html' },
  ];

  it('renders reports table', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ reports: mockReports }),
    });

    render(<ReportsPage />);
    await waitFor(() => {
      expect(screen.getByText('Engagement Report')).toBeInTheDocument();
      expect(screen.getByText('Finding Report')).toBeInTheDocument();
    });
  });

  it('type filter tabs work', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ reports: mockReports }),
    });

    render(<ReportsPage />);
    await waitFor(() => {
      expect(screen.getByText('Engagement Report')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Engagement'));
    await waitFor(() => {
      expect(screen.getByText('Engagement Report')).toBeInTheDocument();
      expect(screen.queryByText('Finding Report')).not.toBeInTheDocument();
    });
  });

  it('generate report button works', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string, init?: any) => {
      if (url === '/api/reports' && !init) {
        return Promise.resolve({ ok: true, json: async () => ({ reports: mockReports }) });
      }
      if (url === '/api/reports/generate') {
        return Promise.resolve({ ok: true, json: async () => ({ id: 'new-report' }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<ReportsPage />);
    await waitFor(() => {
      expect(screen.getByText('Generate Report')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Generate Report'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/reports/generate', expect.objectContaining({ method: 'POST' }));
    });
  });

  it('download button works for ready reports', async () => {
    const mockCreateObjectURL = jest.fn(() => 'blob:url');
    const mockRevokeObjectURL = jest.fn();
    URL.createObjectURL = mockCreateObjectURL;
    URL.revokeObjectURL = mockRevokeObjectURL;

    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url === '/api/reports') {
        return Promise.resolve({ ok: true, json: async () => ({ reports: mockReports }) });
      }
      if (url.includes('/api/reports/r1/download')) {
        return Promise.resolve({ ok: true, blob: async () => new Blob(['pdf']) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<ReportsPage />);
    await waitFor(() => {
      expect(screen.getByText('Engagement Report')).toBeInTheDocument();
    });
  });
});
