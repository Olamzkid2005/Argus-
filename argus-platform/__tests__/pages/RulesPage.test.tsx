import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import RulesPage from '../../src/app/rules/page';

const mockPush = jest.fn();
const mockShowToast = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

jest.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

describe('RulesPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
  });

  const mockRules = [
    { id: 'rule-1', name: 'SQL Injection Check', description: 'Detects SQL injection patterns', severity: 'HIGH', category: 'injection', status: 'active', version: 1, is_community_shared: false, created_at: '2024-01-01' },
    { id: 'rule-2', name: 'XSS Check', description: 'Detects XSS patterns', severity: 'MEDIUM', category: 'custom', status: 'draft', version: 2, is_community_shared: true, created_at: '2024-01-02' },
  ];

  it('renders rules list', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ rules: mockRules }),
    });

    render(<RulesPage />);
    await waitFor(() => {
      expect(screen.getByText('SQL Injection Check')).toBeInTheDocument();
      expect(screen.getByText('XSS Check')).toBeInTheDocument();
    });
  });

  it('status filter works', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ rules: mockRules }),
    });

    render(<RulesPage />);
    await waitFor(() => {
      expect(screen.getByText('active')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('draft'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('status=draft'), expect.anything());
    });
  });

  it('create rule modal opens', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ rules: mockRules }),
    });

    render(<RulesPage />);
    await waitFor(() => {
      expect(screen.getByText('New Rule')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('New Rule'));
    await waitFor(() => {
      expect(screen.getByText('Create Custom Rule')).toBeInTheDocument();
    });
  });

  it('YAML editor renders in create modal', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ rules: mockRules }),
    });

    render(<RulesPage />);
    await waitFor(() => {
      expect(screen.getByText('New Rule')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('New Rule'));
    await waitFor(() => {
      expect(screen.getByText('Rule YAML')).toBeInTheDocument();
      expect(screen.getByDisplayValue('custom-rule-001')).toBeInTheDocument();
    });
  });
});
