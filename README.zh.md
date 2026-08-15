# 盾构刀具管理系统

盾构刀具全生命周期管理系统，用于维护盾构项目、盾构机、刀盘刀位、刀具档案、开仓换刀、磨损、成本、地层和掘进数据，并提供统计分析、移动录入和可选的三维模型入口。

本仓库面向开源维护。公开版本不包含真实工程图纸、项目报告、采购清单、运行凭据或真实项目数据；示例数据应使用虚构或已获授权的内容。

## 主要功能

- 项目和盾构机管理
- 刀具类型、刀位、刀具档案和生命周期追踪
- 开仓记录、换刀明细、环号和地层信息关联
- 磨损状态、异常事件、成本和寿命分析
- 数据分析接口、导出型数据视图和移动端换刀录入
- 基于角色和字段的权限控制
- 可选 AI 助手和 BIMFace 集成（默认不配置、不启用）

## 技术架构

- 后端：Python、Django、Django REST Framework、Channels、Celery
- 前端：Vue 3、TypeScript、Vite、Element Plus、Fast CRUD
- 数据服务：PostgreSQL（推荐）、Redis（Celery/Channels）
- 服务入口：ASGI；需要 WebSocket 时使用 Daphne

后端入口为 `backend/manage.py`，前端位于 `web/`。盾构业务代码位于 `backend/application/shield/` 和 `web/src/views/shield/`。

## 快速开始

完整运行环境建议使用 Python 3.11+、Node.js 18+、PostgreSQL 14+ 和 Redis 6+。

1. 根据 `.env.example` 创建本地配置，并设置唯一的 `DJANGO_SECRET_KEY`、数据库密码和允许的主机名。
2. 安装并启动后端：

   ```powershell
   cd backend
   python -m pip install -r requirements.txt
   python manage.py migrate
   python manage.py init
   python manage.py init_area
   python -m daphne -b 0.0.0.0 -p 8000 application.asgi:application
   ```

3. 安装并启动前端：

   ```powershell
   cd web
   npm install
   npm run dev
   ```

   前端默认访问 `http://localhost:5173`，通过 Vite 将 `/api` 和 `/ws` 代理到后端。

Docker 配置位于 `docker-compose.yml` 和 `docker-compose.db.yml`。在非本机环境使用前，请检查环境变量、端口和挂载目录。

## 配置与安全

- 不要提交 `.env`、`backend/.env*`、`web/.env*`、数据库 dump、日志、构建产物、API Key、BIMFace 标识或真实工程文件。
- 使用 `backend/conf/env.example.py` 和 `web/.env.*.example` 作为模板，不要把真实值写入模板。
- 生产环境必须设置 `DJANGO_SECRET_KEY`；公开代码中的默认值仅用于开发启动。
- AI、AMap 和 BIMFace 集成均需要运行时凭据，默认保持可选和关闭状态。
- 导入的 CSV/JSON 可能包含敏感信息，只发布虚构或明确获准公开的示例。

## 检查与测试

```powershell
cd backend
python manage.py check
python manage.py test application.shield.tests

cd ../web
npm run build
```

涉及页面、图表或导出的改动，还需要在浏览器或实际导出结果中进行视觉检查。

## 许可证与上游项目

本项目使用 Apache License 2.0。项目包含基于 [Django-Vue3-Admin](https://gitee.com/huge-dream/django-vue3-admin) 的代码，相关版权和署名保留在 `NOTICE` 中。重新发布修改版本前，请阅读 `LICENSE` 和 `NOTICE`。

## 贡献与安全报告

开发约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，漏洞报告方式见 [`SECURITY.md`](SECURITY.md)。请不要在 Issue 中公开凭据、客户数据、图纸或其他内部资料。

版本记录见 [`CHANGELOG.md`](CHANGELOG.md)，路线图和讨论请使用 GitHub Issue。
