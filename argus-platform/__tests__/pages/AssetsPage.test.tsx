import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AssetsPage from '../../src/app/assets/page';

const mockPush = jest.fn();
const mockShowToast = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

jest.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

describe('AssetsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
  });

  const mockAssets = [
    { id: 'a1', asset_type: 'domain', identifier: 'example.com', display_name: 'Example', description: '', risk_score: 5, risk_level: 'MEDIUM', criticality: 'medium', lifecycle_status: 'active', discovered_at: '2024-01-01', last_scanned_at: '2024-01-02', verified: true },
    { id: 'a2', asset_type: 'endpoint', identifier: '/api/users', display_name: 'Users API', description: '', risk_score: 8, risk_level: 'HIGH', criticality: 'high', lifecycle_status: 'active', discovered_at: '2024-01-01', last_scanned_at: null, verified: false },
  ];

  it('renders assets table', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ assets: mockAssets, stats: { total: 2, critical: 0, high: 1, active: 2 } }),
    });

    render(<AssetsPage />);
    await waitFor(() => {
      expect(screen.getByText('Example')).toBeInTheDocument();
      expect(screen.getByText('Users API')).toBeInTheDocument();
    });
  });

  it('renders stats cards', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ assets: mockAssets, stats: { total: 2, critical: 0, high: 1, active: 2 } }),
    });

    render(<AssetsPage />);
    await waitFor(() => {
      expect(screen.getByText('Total Assets')).toBeInTheDocument();
      expect(screen.getByText('Critical Risk')).toBeInTheDocument();
      expect(screen.getByText('High Risk')).toBeInTheDocument();
      expect(screen.getByText('Active')).toBeInTheDocument();
    });
  });

  it('type filter works', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ assets: mockAssets, stats: { total: 2, critical: 0, high: 1, active: 2 } }),
    });

    render(<AssetsPage />);
    await waitFor(() => {
      expect(screen.getByText('all')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('domain'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('type=domain'), expect.anything());
    });
  });

  it('create asset modal opens', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ assets: mockAssets, stats: { total: 2, critical: 0, high: 1, active: 2 } }),
    });

    render(<AssetsPage />);
    await waitFor(() => {
      expect(screen.getByText('Add Asset')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Add Asset'));
    await waitFor(() => {
      expect(screen.getByText('Add Asset', { selector: 'h2' })).toBeInTheDocument();
    });
  });
});
