import React from "react";
import { render, fireEvent } from "@testing-library/react";
import NotificationCenter from "@/components/ui-custom/NotificationCenter";

jest.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

jest.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: any) => <div data-testid="popover">{children}</div>,
  PopoverTrigger: ({ children }: any) => (
    <div data-testid="popover-trigger">{children}</div>
  ),
  PopoverContent: ({ children }: any) => (
    <div data-testid="popover-content">{children}</div>
  ),
}));

jest.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: any) => (
    <div data-testid="scroll-area">{children}</div>
  ),
}));

const mockUseNotifications = jest.fn();
jest.mock("@/hooks/useNotifications", () => ({
  useNotifications: (...args: any[]) => mockUseNotifications(...args),
}));

jest.mock("date-fns", () => ({
  formatDistanceToNow: () => "2 min ago",
}));

beforeEach(() => {
  mockUseNotifications.mockReset();
});

it("renders bell icon button", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { getByLabelText } = render(<NotificationCenter />);
  expect(getByLabelText("Notifications")).toBeInTheDocument();
});

it("shows unread count badge when there are unread notifications", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "1",
        type: "scan_complete",
        title: "Scan Complete",
        message: "Scan finished",
        timestamp: new Date().toISOString(),
        read: false,
      },
    ],
    unreadCount: 3,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { getByText } = render(<NotificationCenter />);
  expect(getByText("3")).toBeInTheDocument();
});

it("does not show badge when unread count is zero", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { queryByText } = render(<NotificationCenter />);
  expect(queryByText("0")).not.toBeInTheDocument();
});

it("shows empty state when no notifications", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { getByText } = render(<NotificationCenter />);
  expect(getByText("No notifications")).toBeInTheDocument();
  expect(getByText("You're all caught up")).toBeInTheDocument();
});

it("renders notification list", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "1",
        type: "scan_complete",
        title: "Scan Completed",
        message: "Target scan finished successfully",
        timestamp: new Date().toISOString(),
        read: false,
      },
      {
        id: "2",
        type: "finding",
        title: "New Finding",
        message: "Critical vulnerability discovered",
        timestamp: new Date().toISOString(),
        read: true,
      },
    ],
    unreadCount: 1,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { getByText, getAllByText } = render(<NotificationCenter />);
  expect(getByText("Scan Completed")).toBeInTheDocument();
  expect(getByText("Target scan finished successfully")).toBeInTheDocument();
  expect(getByText("New Finding")).toBeInTheDocument();
  expect(getByText("Critical vulnerability discovered")).toBeInTheDocument();
  expect(getAllByText("2 min ago")).toHaveLength(2);
});

it("calls markAsRead when 'Mark as read' is clicked", () => {
  const markAsRead = jest.fn();
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "1",
        type: "system",
        title: "System Alert",
        message: "System maintenance scheduled",
        timestamp: new Date().toISOString(),
        read: false,
      },
    ],
    unreadCount: 1,
    markAsRead,
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { getByText } = render(<NotificationCenter />);
  fireEvent.click(getByText("Mark as read"));
  expect(markAsRead).toHaveBeenCalledTimes(1);
  expect(markAsRead).toHaveBeenCalledWith("1");
});

it("calls removeNotification when dismiss button is clicked", () => {
  const removeNotification = jest.fn();
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "2",
        type: "finding",
        title: "New Finding",
        message: "Critical vulnerability discovered",
        timestamp: new Date().toISOString(),
        read: true,
      },
    ],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification,
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { getByLabelText } = render(<NotificationCenter />);
  fireEvent.click(getByLabelText("Dismiss notification"));
  expect(removeNotification).toHaveBeenCalledTimes(1);
  expect(removeNotification).toHaveBeenCalledWith("2");
});

it("calls markAllAsRead when 'Mark all read' is clicked", () => {
  const markAllAsRead = jest.fn();
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "1",
        type: "status_change",
        title: "Status Changed",
        message: "Engagement status updated",
        timestamp: new Date().toISOString(),
        read: false,
      },
    ],
    unreadCount: 1,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead,
    dismissAll: jest.fn(),
  });

  const { getByText } = render(<NotificationCenter />);
  fireEvent.click(getByText("Mark all read"));
  expect(markAllAsRead).toHaveBeenCalledTimes(1);
});

it("calls dismissAll when 'Clear all' is clicked", () => {
  const dismissAll = jest.fn();
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "1",
        type: "scan_complete",
        title: "Scan Completed",
        message: "Done",
        timestamp: new Date().toISOString(),
        read: true,
      },
    ],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll,
  });

  const { getByText } = render(<NotificationCenter />);
  fireEvent.click(getByText("Clear all"));
  expect(dismissAll).toHaveBeenCalledTimes(1);
});

it("does not show 'Mark all read' when no unread notifications", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [
      {
        id: "1",
        type: "scan_complete",
        title: "Scan Completed",
        message: "Done",
        timestamp: new Date().toISOString(),
        read: true,
      },
    ],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { queryByText } = render(<NotificationCenter />);
  expect(queryByText("Mark all read")).not.toBeInTheDocument();
});

it("does not show 'Clear all' when no notifications", () => {
  mockUseNotifications.mockReturnValue({
    notifications: [],
    unreadCount: 0,
    markAsRead: jest.fn(),
    removeNotification: jest.fn(),
    markAllAsRead: jest.fn(),
    dismissAll: jest.fn(),
  });

  const { queryByText } = render(<NotificationCenter />);
  expect(queryByText("Clear all")).not.toBeInTheDocument();
});
