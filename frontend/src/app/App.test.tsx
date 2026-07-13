import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "./App";

function renderApp(path = "/assignments") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  it("显示作业空状态", () => {
    renderApp();

    expect(screen.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "还没有作业" })).toBeVisible();
  });

  it("两个创建入口进入同一创建状态", () => {
    renderApp();

    fireEvent.click(screen.getAllByRole("button", { name: "创建作业" })[1]);
    expect(screen.getByRole("heading", { name: "创建新作业" })).toBeVisible();
  });

  it("可以切换英文界面", () => {
    renderApp();

    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    expect(
      screen.getByRole("complementary", { name: "Main navigation" }),
    ).toBeVisible();
    expect(screen.getByText("Teacher")).toBeVisible();
    expect(document.documentElement.lang).toBe("en");
  });

  it("导航会切换到批改任务页面", () => {
    renderApp();

    fireEvent.click(screen.getByRole("link", { name: "批改任务" }));
    expect(screen.getByRole("heading", { name: "批改任务" })).toBeVisible();
  });

  it("账户入口会显示当前账户状态", () => {
    renderApp();

    fireEvent.click(screen.getByRole("button", { name: "教师" }));
    expect(screen.getByRole("heading", { name: "当前账户" })).toBeVisible();
    expect(screen.getByText("角色：教师")).toBeVisible();
  });
});
