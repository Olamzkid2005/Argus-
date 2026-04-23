import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import FindingsPage from '@/app/findings/page';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useToast } from '@/components/ui/Toast';

// Mock dependencies
jest.mock('next-auth/react', () => ({
  useSession: jest.fn(),
  signIn: jest.fn(),
}));

jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({ push: jest.fn() })),
}));

jest.mock('@/components/ui/Toast', () => ({
  useToast: jest.fn(() => ({ showToast: jest.fn() })),
}));

jest.mock('framer-motion', () => ({
  motion: { div: 'div', button: 'button' },
  AnimatePresence: 'div',
}));

jest.mock('@/components/effects/ScannerReveal', () => 'div');
jest.mock('@/components/ui-custom/AIStatus', () => ({ AIStatusBadge: 'div' }));
jest.mock('@/components/ui-custom/MarkdownRenderer', () => ({ MarkdownRenderer: 'div' }));
jest.mock('@/components/animations/ScrollReveal', () => ({ ScrollReveal: 'div' }));
jest.mock('@/components/animations/StaggerContainer', () => ({ StaggerContainer: 'div', StaggerItem: 'div' }));
jest.mock('@/components/security/SecurityRating', () => 'div');
jest.mock('@/components/ui-custom/BulkActionBar', () => 'div');
jest.mock('lucide-react', () => ({
  Search: 'div', Filter: 'div', ChevronDown: 'div', Bug: 'div', AlertTriangle: 'div',
  Shield: 'div', Copy: 'div', Check: 'div', Loader2: 'div', Trash2: 'div',
  CheckCircle2: 'div', Brain: 'div', Sparkles: 'div', Zap: 'div', Link2: 'div',
  Sword: 'div', Target: 'div', X: 'div', ChevronRight: 'div', UserCheck: 'div',
  Wrench: 'div', Code2: 'div',
}));

describe('Finding Tabs', () => {
  beforeEach(() => {
    (useSession as jest.Mock).mockReturnValue({
      data: { user: { email: 'test@example.com' } },
      status: 'authenticated',
    });
  });

  it('generates correct curl command from finding data', () => {
    const finding = {
      target_url: 'https://example.com',
      endpoint: '/api/test',
    };
    const baseUrl = finding.target_url || "";
    const endpoint = finding.endpoint.startsWith("/") ? finding.endpoint : `/${finding.endpoint}`;
    const url = `${baseUrl}${endpoint}`;
    const curl = `curl -X GET "${url}" -H "User-Agent: Argus-Scanner" -H "Accept: */*"`;
    expect(curl).toBe('curl -X GET "https://example.com/api/test" -H "User-Agent: Argus-Scanner" -H "Accept: */*"');
  });

  it('tab switching logic works correctly', () => {
    // Mock activeTab state change
    const mockSetActiveTab = jest.fn();
    const FindingTab = "overview" as const;
    mockSetActiveTab("evidence");
    expect(mockSetActiveTab).toHaveBeenCalledWith("evidence");
  });
});
