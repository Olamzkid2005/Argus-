import React from "react";
import { render, getByText, queryByText, fireEvent } from "@testing-library/react";

// Mock modules before importing component
jest.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

let EmptyState: React.ComponentType<{
  icon?: React.ReactNode;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
}>;

beforeEach(() => {
  jest.resetModules();
  EmptyState = require("@/components/ui-custom/EmptyState").default;
});

it("renders with required props only", () => {
  const { getByText } = render(
    React.createElement(EmptyState, { title: "No items found" })
  );
  expect(getByText("No items found")).toBeInTheDocument();
});

it("renders with icon", () => {
  const { container, getByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      icon: React.createElement("span", null, "🔍"),
    })
  );
  expect(getByText("No items")).toBeInTheDocument();
  expect(container.querySelector("span")).toBeInTheDocument();
});

it("renders without icon when not provided", () => {
  const { container, getByText } = render(
    React.createElement(EmptyState, { title: "No items" })
  );
  expect(getByText("No items")).toBeInTheDocument();
  const iconContainer = container.querySelector(".rounded-full");
  expect(iconContainer).not.toBeInTheDocument();
});

it("renders description when provided", () => {
  const { getByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      description: "Try adjusting your filters",
    })
  );
  expect(getByText("Try adjusting your filters")).toBeInTheDocument();
});

it("calls onAction when primary action button is clicked", () => {
  const onAction = jest.fn();
  const { getByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      actionLabel: "Create New",
      onAction,
    })
  );
  fireEvent.click(getByText("Create New"));
  expect(onAction).toHaveBeenCalledTimes(1);
});

it("does not render primary button without onAction", () => {
  const { queryByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      actionLabel: "Create New",
    })
  );
  expect(queryByText("Create New")).not.toBeInTheDocument();
});

it("calls onSecondaryAction when secondary link is clicked", () => {
  const onSecondaryAction = jest.fn();
  const { getByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      secondaryActionLabel: "Learn more",
      onSecondaryAction,
    })
  );
  fireEvent.click(getByText("Learn more"));
  expect(onSecondaryAction).toHaveBeenCalledTimes(1);
});

it("does not render secondary link without onSecondaryAction", () => {
  const { queryByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      secondaryActionLabel: "Learn more",
    })
  );
  expect(queryByText("Learn more")).not.toBeInTheDocument();
});

it("renders both action buttons together", () => {
  const onAction = jest.fn();
  const onSecondaryAction = jest.fn();
  const { getByText } = render(
    React.createElement(EmptyState, {
      title: "No items",
      actionLabel: "Retry",
      onAction,
      secondaryActionLabel: "Cancel",
      onSecondaryAction,
    })
  );
  fireEvent.click(getByText("Retry"));
  fireEvent.click(getByText("Cancel"));
  expect(onAction).toHaveBeenCalledTimes(1);
  expect(onSecondaryAction).toHaveBeenCalledTimes(1);
});
