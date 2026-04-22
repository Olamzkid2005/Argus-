import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Home from '../../src/app/page';

// Override mocks for landing page
jest.mock('next-auth/react', () => ({
  useSession: () => ({ data: null, status: 'unauthenticated' }),
  signIn: jest.fn(),
}));

describe('LandingPage', () => {
  it('renders hero section with headline', async () => {
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText('Build.', { exact: false })).toBeInTheDocument();
    });
    expect(screen.getByText('Scale.', { exact: false })).toBeInTheDocument();
  });

  it('renders navigation links', async () => {
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText('Platform')).toBeInTheDocument();
      expect(screen.getByText('Models')).toBeInTheDocument();
      expect(screen.getByText('Developers')).toBeInTheDocument();
      expect(screen.getByText('Pricing')).toBeInTheDocument();
    });
  });

  it('renders CTA buttons', async () => {
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText('Get Started Free')).toBeInTheDocument();
      expect(screen.getByText('Talk to our team')).toBeInTheDocument();
    });
  });

  it('renders features section', async () => {
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText('Platform Capabilities')).toBeInTheDocument();
      expect(screen.getByText('Code Assistance')).toBeInTheDocument();
      expect(screen.getByText('Conversational AI')).toBeInTheDocument();
      expect(screen.getByText('Multimodal')).toBeInTheDocument();
      expect(screen.getByText('Enterprise RAG')).toBeInTheDocument();
    });
  });

  it('renders footer', async () => {
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText('Product')).toBeInTheDocument();
      expect(screen.getByText('Developers')).toBeInTheDocument();
      expect(screen.getByText('Company')).toBeInTheDocument();
      expect(screen.getByText('Legal')).toBeInTheDocument();
    });
  });
});
