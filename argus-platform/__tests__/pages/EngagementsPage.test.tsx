import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import EngagementsPage from '../../src/app/engagements/page';

const mockPush = jest.fn();
const mockShowToast = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

jest.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

describe('EngagementsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
  });

  it('scan type toggle works', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ engagements: [], settings: {} }) });
    render(<EngagementsPage />);
    await waitFor(() => {
      expect(screen.getByText('Web Application')).toBeInTheDocument();
      expect(screen.getByText('Repository')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Repository'));
    expect(screen.getByPlaceholderText('username/repository')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Web Application'));
    expect(screen.getByPlaceholderText('https://target.com')).toBeInTheDocument();
  });

  it('target input renders', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ engagements: [] }) });
    render(<EngagementsPage />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText('https://target.com')).toBeInTheDocument();
    });
  });

  it('aggressiveness selector works', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ engagements: [] }) });
    render(<EngagementsPage />);
    await waitFor(() => {
      expect(screen.getByText('Default')).toBeInTheDocument();
      expect(screen.getByText('High')).toBeInTheDocument();
      expect(screen.getByText('Extreme')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('High'));
    // The submit should now use high aggressiveness
    expect(screen.getByText('High').closest('button')).toHaveClass('border-amber-500');
  });

  it('submit button creates engagement via API', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string, init?: any) => {
      if (url === '/api/settings') {
        return Promise.resolve({ ok: true, json: async () => ({ settings: {} }) });
      }
      if (url === '/api/engagements') {
        return Promise.resolve({ ok: true, json: async () => ({ engagements: [] }) });
      }
      if (url === '/api/engagement/create') {
        return Promise.resolve({ ok: true, json: async () => ({ engagement: { id: 'eng-123' } }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<EngagementsPage />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText('https://target.com')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText('https://target.com'), { target: { value: 'https://example.com' } });
    fireEvent.click(screen.getByRole('button', { name: /launch engagement/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/engagement/create', expect.objectContaining({ method: 'POST' }));
    });
  });

  it('shows progress indicator during creation', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url === '/api/settings') {
        return Promise.resolve({ ok: true, json: async () => ({ settings: {} }) });
      }
      if (url === '/api/engagements') {
        return Promise.resolve({ ok: true, json: async () => ({ engagements: [] }) });
      }
      if (url === '/api/engagement/create') {
        return new Promise((resolve) => {
          setTimeout(() => resolve({ ok: true, json: async () => ({ engagement: { id: 'eng-123' } }) }), 100);
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<EngagementsPage />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText('https://target.com')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText('https://target.com'), { target: { value: 'https://example.com' } });
    fireEvent.click(screen.getByRole('button', { name: /launch engagement/i }));

    await waitFor(() => {
      expect(screen.getByText(/initializing|validating|creating/i)).toBeInTheDocument();
    });
  });
});
