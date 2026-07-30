import { expect, test } from "../frontend/node_modules/@playwright/test";

test("邀请、登录、作业、上传、批量评分、复核和 Excel 导出完整流程", async ({
  page,
  request,
}) => {
  const browserMessages: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      browserMessages.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => browserMessages.push(`pageerror: ${error.message}`));
  await request.post("http://127.0.0.1:54321/mock/reset");

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "欢迎登录" })).toBeVisible();
  await page.getByLabel("邮箱").fill("admin@example.test");
  await page.getByLabel("密码").fill("stage14-local-password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "作业", exact: true })).toBeVisible();

  await page.goto("/admin/users");
  await page.getByRole("button", { name: "邀请教师" }).click();
  await page.getByLabel("姓名").fill("测试教师");
  await page.getByLabel("邮箱").fill("teacher@example.test");
  await page.getByRole("button", { name: "发送邀请" }).click();
  await expect(page.getByText("teacher@example.test")).toBeVisible();

  await page.getByRole("button", { name: "系统管理员" }).click();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "欢迎登录" })).toBeVisible();
  await page.getByLabel("邮箱").fill("teacher@example.test");
  await page.getByLabel("密码").fill("stage14-local-password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("button", { name: "测试教师" })).toBeVisible();
  await page.goto("/assignments");
  await expect(page.getByRole("heading", { name: "作业", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "创建作业" }).first().click();
  await page.getByLabel("作业名称").fill("Stage 14 essay");
  await page.getByRole("textbox", { name: "题目要求" }).fill("Write an argumentative essay.");
  await page
    .getByRole("textbox", { name: "原始评分标准" })
    .fill("Content 20 points.");
  await page.getByLabel("总分").fill("20");
  await page.getByLabel("评分步长").fill("1");
  await page.getByRole("button", { name: "保存并继续" }).click();
  await expect(page.getByRole("heading", { name: "设置评分标准" })).toBeVisible();
  await page.getByLabel("结构化模型").selectOption({ label: "Stage 14 provider · safe-test-model" });
  await page.getByRole("button", { name: "生成结构化草稿" }).click();
  await expect(page.getByRole("heading", { name: "Content" })).toBeVisible();
  await page.getByRole("button", { name: "确认评分标准" }).click();
  await expect(page.getByText("当前版本已确认并冻结。")).toBeVisible();

  await page.getByRole("link", { name: "上传论文" }).click();
  await page.getByLabel("选择 DOCX/PDF 文件").setInputFiles({
    name: "stage14.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("PK-stage14-local-browser-fixture"),
  });
  await page.getByRole("button", { name: "开始上传" }).click();
  await expect(page.getByLabel("已保存论文").getByText("解析完成")).toBeVisible();
  await page.getByRole("checkbox", { name: "选择 stage14.docx" }).check();
  await page.getByRole("button", { name: "创建批改任务" }).click();
  await expect(page.getByRole("heading", { name: "批改任务" })).toBeVisible();

  const exportHref = await page.getByRole("link", { name: "导出成绩" }).getAttribute("href");
  expect(exportHref).toMatch(/^\/exports\?jobId=/);
  await page.getByRole("link", { name: "进入复核" }).click();
  await expect(page.getByRole("heading", { name: "stage14.docx" })).toBeVisible();
  const reviewTab = page.getByRole("tab", { name: "评分复核" });
  if (await reviewTab.isVisible()) {
    await reviewTab.click();
  }
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("草稿已保存。", { exact: true })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "确认最终成绩" }).click();
  await expect(page.getByText("该论文已确认，内容只读。").first()).toBeVisible();

  await page.goto(exportHref as string);
  await page.getByRole("radio", { name: /^最终成绩/ }).check();
  await page.getByRole("button", { name: "生成最终工作簿" }).click();
  await expect(page.getByText("已完成")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /下载/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("stage14-final.xlsx");

  expect(browserMessages).toEqual([]);
  const bodyWidth = await page.locator("body").evaluate((body) => body.scrollWidth);
  const viewportWidth = await page.locator("body").evaluate((body) => body.clientWidth);
  expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
});
