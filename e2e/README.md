# 阶段 14 浏览器测试边界

- `npm --prefix frontend run e2e:local` 只访问 `127.0.0.1:54321/mock`，覆盖邀请、登录、创建作业、Rubric、上传、批量评分、教师复核和 Excel 下载。它验证浏览器与前端编排，不代表真实 Supabase、Redis、Storage、模型、Sites 或 Mac 部署通过。
- `npm --prefix frontend run e2e:real` 只接受 HTTPS `E2E_REAL_BASE_URL`。邀请回调、设密和首次登录必须由人工浏览器证据完成；自动脚本只使用已完成激活的教师 A、另一名教师 B、用户提供的题目/Rubric/单篇论文、已启用模型和显式写入/一次完整模型流程授权，全部属于真实数据写入。
- 真实脚本只创建一次批改任务（`create_job_count=1`）：先以桌面视口完成 Rubric、单篇评分、复核、Excel 下载和同一签名 URL 过期，再切换到 `390 × 844` 复用同一批次，最后由教师 B 验证看不到教师 A 的资源。任何 Console error、warning、页面异常或横向溢出都会失败。
- 本地 Mock 失败截图和 trace 只保存在被 `.gitignore` 排除的 `test-results/`。真实验收强制关闭 screenshot、trace 和 video，避免把论文、反馈、邮箱、Token、对象路径或签名 URL写入失败产物。
