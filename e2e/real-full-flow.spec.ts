import { existsSync, readFileSync } from "node:fs";
import { basename, isAbsolute } from "node:path";

import { expect, test, type Page } from "../frontend/node_modules/@playwright/test";

import { applySitesBypassHeader } from "./stage14-sites-bypass";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`真实浏览器验收缺少 ${name}`);
  return value;
}

function requiredAbsoluteFile(name: string): string {
  const value = required(name);
  if (!isAbsolute(value) || !existsSync(value)) {
    throw new Error(`${name} 必须是已存在的绝对文件路径`);
  }
  return value;
}

async function login(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "作业", exact: true })).toBeVisible();
}

if (process.env.E2E_REAL_WRITES !== "I_ACCEPT_STAGE14_TEST_WRITES") {
  throw new Error("真实浏览器验收必须显式确认 E2E_REAL_WRITES");
}
if (process.env.E2E_REAL_MODEL_CALLS !== "I_ACCEPT_ONE_COMPLETE_MODEL_FLOW") {
  throw new Error("真实浏览器验收会产生一次 Rubric 和单篇评分流程，必须显式确认模型费用");
}

const teacherEmail = required("E2E_REAL_TEACHER_EMAIL");
const teacherPassword = required("E2E_REAL_TEACHER_PASSWORD");
const teacherDisplayName = required("E2E_REAL_TEACHER_DISPLAY_NAME");
const otherTeacherEmail = required("E2E_REAL_OTHER_TEACHER_EMAIL");
const otherTeacherPassword = required("E2E_REAL_OTHER_TEACHER_PASSWORD");
const modelLabel = required("E2E_REAL_MODEL_LABEL");
const assignmentTitle = required("E2E_REAL_ASSIGNMENT_TITLE");
const instructionsPath = requiredAbsoluteFile("E2E_REAL_INSTRUCTIONS_PATH");
const rubricPath = requiredAbsoluteFile("E2E_REAL_RUBRIC_PATH");
const paperPath = requiredAbsoluteFile("E2E_REAL_PAPER_PATH");
const totalScore = required("E2E_REAL_TOTAL_SCORE");
const scoreStep = required("E2E_REAL_SCORE_STEP");

test("一个真实批次完成桌面流程、手机复用和双教师隔离", async ({ page }) => {
  let browserErrorCount = 0;
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      browserErrorCount += 1;
    }
  });
  page.on("pageerror", () => {
    browserErrorCount += 1;
  });

  await applySitesBypassHeader(page);
  await login(page, teacherEmail, teacherPassword);

  await page.getByRole("link", { name: "创建作业" }).first().click();
  await page.getByLabel("作业名称").fill(assignmentTitle);
  await page.getByLabel("从 .txt/.md 读取题目要求").setInputFiles(instructionsPath);
  await page.getByLabel("从 .txt/.md 读取原始评分标准").setInputFiles(rubricPath);
  await page.getByLabel("总分").fill(totalScore);
  await page.getByLabel("评分步长").fill(scoreStep);
  await page.getByRole("button", { name: "保存并继续" }).click();
  await expect(page.getByRole("heading", { name: "设置评分标准" })).toBeVisible();
  await page.getByLabel("结构化模型").selectOption({ label: modelLabel });
  await page.getByRole("button", { name: "生成结构化草稿" }).click();
  const confirmRubric = page.getByRole("button", { name: "确认评分标准" });
  await expect(confirmRubric).toBeEnabled({ timeout: 180_000 });
  await confirmRubric.click();
  await expect(page.getByText("当前版本已确认并冻结。")).toBeVisible();

  await page.getByRole("link", { name: "上传论文" }).click();
  await page.getByLabel("选择 DOCX/PDF 文件").setInputFiles(paperPath);
  await page.getByRole("button", { name: "开始上传" }).click();
  await expect(page.getByLabel("已保存论文").getByText("解析完成")).toBeVisible({
    timeout: 120_000,
  });
  const filename = basename(paperPath);
  await page.getByRole("checkbox", { name: `选择 ${filename}` }).check();
  await page.getByRole("button", { name: "创建批改任务" }).click();
  await expect(page.getByRole("heading", { name: "批改任务" })).toBeVisible();

  const reviewLink = page.getByRole("link", { name: "进入复核" });
  await expect(reviewLink).toBeVisible({ timeout: 600_000 });
  const exportHref = await page.getByRole("link", { name: "导出成绩" }).getAttribute("href");
  expect(exportHref).toMatch(/^\/exports\?jobId=/);
  const jobId = new URL(exportHref as string, "https://stage14.invalid").searchParams.get("jobId");
  expect(jobId).toMatch(/^[0-9a-f-]{36}$/);
  await reviewLink.click();
  await expect(page.getByRole("heading", { name: filename })).toBeVisible();
  const reviewTab = page.getByRole("tab", { name: "评分复核" });
  if (await reviewTab.isVisible()) await reviewTab.click();
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("草稿已保存。", { exact: true })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "确认最终成绩" }).click();
  await expect(page.getByText("该论文已确认，内容只读。").first()).toBeVisible();

  await page.goto(exportHref as string);
  await page.getByRole("radio", { name: /^最终成绩/ }).check();
  await page.getByRole("button", { name: "生成最终工作簿" }).click();
  await expect(page.getByText("已完成")).toBeVisible({ timeout: 300_000 });
  const downloadResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/exports/`) &&
      response.url().endsWith("/download"),
  );
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /下载/ }).click();
  const [downloadResponse, download] = await Promise.all([
    downloadResponsePromise,
    downloadPromise,
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
  const downloadedPath = await download.path();
  expect(downloadedPath).not.toBeNull();
  const workbookBytes = readFileSync(downloadedPath as string);
  expect(workbookBytes.length).toBeGreaterThan(1_000);
  expect(workbookBytes.subarray(0, 2).toString("ascii")).toBe("PK");

  const downloadPayload = (await downloadResponse.json()) as {
    download_url: string;
    expires_in_seconds: number;
  };
  expect(downloadPayload.expires_in_seconds).toBeGreaterThan(0);
  await page.waitForTimeout((downloadPayload.expires_in_seconds + 5) * 1_000);
  let expiredDownload;
  try {
    expiredDownload = await page.request.get(downloadPayload.download_url);
  } catch {
    throw new Error("stage14_signed_url_expiry_probe_failed");
  }
  expect(expiredDownload.status()).toBeGreaterThanOrEqual(400);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/grading-jobs");
  await expect(page.getByText(assignmentTitle, { exact: true })).toBeVisible();
  await page.goto(exportHref as string);
  await expect(page.getByRole("heading", { name: "成绩导出" })).toBeVisible();
  await expect(page.getByRole("button", { name: /下载/ })).toBeVisible();
  const dimensions = await page.locator("body").evaluate((body) => ({
    clientWidth: body.clientWidth,
    scrollWidth: body.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);

  await page.getByRole("button", { name: teacherDisplayName }).click();
  await page.getByRole("button", { name: "退出登录" }).click();
  await login(page, otherTeacherEmail, otherTeacherPassword);
  await expect(page.getByText(assignmentTitle, { exact: true })).toHaveCount(0);
  await page.goto("/grading-jobs");
  await expect(page.getByText(assignmentTitle, { exact: true })).toHaveCount(0);
  await page.goto(`/exports?jobId=${jobId}`);
  await expect(page.getByText(assignmentTitle, { exact: true })).toHaveCount(0);

  expect(browserErrorCount).toBe(0);
});
