# 生产环境认证配置

项目使用 HttpOnly Cookie 保存 access/refresh token，并使用 `rag_csrf_token` Cookie + `X-CSRF-Token` 请求头完成 CSRF 双提交校验。

生产环境必须满足以下条件：

1. 通过 HTTPS 提供前端和后端服务。
2. 设置 `AUTH_COOKIE_SECURE=true`，否则 Cookie 会允许在非 HTTPS 链路发送。
3. 设置 `CORS_ALLOWED_ORIGINS` 为实际前端完整 origin，多个 origin 用逗号分隔，例如 `https://notes.example.com`。不要填写 `*`，因为启用了 credentialed requests。
4. 前端和后端使用同一站点或可正确共享 Cookie 的域名策略；反向代理需要转发 `Host`、`Origin` 和 `X-Forwarded-Proto`。
5. 修改 `JWT_SECRET_KEY`、数据库密码、MinIO 密码和 `MCP_AUDIT_TOKEN`，不要使用示例值。

本地 Docker 开发可以保持：

```env
AUTH_COOKIE_SECURE=false
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

切换生产配置后需要重启 backend，使 Settings 重新读取环境变量。浏览器开发者工具中应能看到 access/refresh Cookie 的 `HttpOnly` 和 `Secure` 标记，以及请求带有 `X-CSRF-Token`。
