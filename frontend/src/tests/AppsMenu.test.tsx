/**
 * AppsMenu component tests.
 *
 * We mock the useApps hook to control what TanStack Query returns,
 * and verify the button visibility and click behaviour.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// Minimal i18n instance for tests
const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "en",
  resources: {
    en: {
      translation: {
        "topbar.apps_menu": "Applications",
      },
    },
  },
  interpolation: { escapeValue: false },
});

// Mock the useApps hook before importing the component
vi.mock("@/hooks/useApps");

import { AppsMenu } from "@/components/AppsMenu";
import type { AppsResponse } from "@/schemas/apps";
import { useApps } from "@/hooks/useApps";

// Type the mocked hook
const mockUseApps = vi.mocked(useApps);

function renderAppsMenu() {
  return render(
    <I18nextProvider i18n={i18nTest}>
      <MantineProvider>
        <AppsMenu />
      </MantineProvider>
    </I18nextProvider>,
  );
}

describe("AppsMenu", () => {
  beforeEach(() => {
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when apps list is empty", () => {
    mockUseApps.mockReturnValue({
      data: { urls: [] } as AppsResponse,
      isLoading: false,
    } as ReturnType<typeof useApps>);

    renderAppsMenu();
    expect(screen.queryByRole("button", { name: /applications/i })).toBeNull();
  });

  it("renders nothing while loading", () => {
    mockUseApps.mockReturnValue({
      data: undefined,
      isLoading: true,
    } as ReturnType<typeof useApps>);

    renderAppsMenu();
    expect(screen.queryByRole("button", { name: /applications/i })).toBeNull();
  });

  it("renders the trigger button when apps are present", () => {
    mockUseApps.mockReturnValue({
      data: {
        urls: [
          {
            key: "docker",
            label: "Docker",
            icon: "https://docker-agflow.yoops.org/favicon.ico",
            url: "https://docker-agflow.yoops.org/",
          },
        ],
      } as AppsResponse,
      isLoading: false,
    } as ReturnType<typeof useApps>);

    renderAppsMenu();
    expect(
      screen.getByRole("button", { name: /applications/i }),
    ).toBeInTheDocument();
  });

  it("opens app in new tab on menu item click", async () => {
    const appUrl = "https://docker-agflow.yoops.org/";

    mockUseApps.mockReturnValue({
      data: {
        urls: [
          {
            key: "docker",
            label: "Docker",
            icon: "https://docker-agflow.yoops.org/favicon.ico",
            url: appUrl,
          },
        ],
      } as AppsResponse,
      isLoading: false,
    } as ReturnType<typeof useApps>);

    renderAppsMenu();

    // Open the menu
    const trigger = screen.getByRole("button", { name: /applications/i });
    fireEvent.click(trigger);

    // Click the menu item
    const menuItem = await screen.findByText("Docker");
    fireEvent.click(menuItem);

    expect(window.open).toHaveBeenCalledWith(
      appUrl,
      "_blank",
      "noopener,noreferrer",
    );
  });
});
