# office-agent-mvp 常用命令（V2.1）
# Windows 默认无 make：直接按 README「开发命令」逐条复制；Git Bash + make 亦可。
# 依赖：Python 3.13（.venv）、Node 20+、Docker（可选）
# 镜像源：本机实测官方 PyPI / 清华源不可达，统一用阿里云镜像。

PY ?= .venv/Scripts/python.exe
NPM ?= npm
BASE_URL ?= http://127.0.0.1:8004
PIP_INDEX ?= https://mirrors.aliyun.com/pypi/simple
# Windows 环境 NO_PROXY 含 [::1] 会让 httpx 报 Invalid port: ':1]'
NO_PROXY ?= localhost,127.0.0.1
no_proxy ?= $(NO_PROXY)
export NO_PROXY no_proxy
# 有人把 PYTHONHOME 设成驱动盘根（如 E:\）——它会让 .venv 的 python 去别处找
# 标准库，版本一对不上就在 import re 时抛 "AssertionError: SRE module mismatch"。
# PYTHONPATH 同理：残留的 shim 目录会盖掉真实包。两条都在这里摘掉。
unexport PYTHONHOME
unexport PYTHONPATH

BACKEND_PYPROJECT := backend/pyproject.toml
FRONTEND_PKG := frontend/package.json
MOCK_DB := data/b5_mock.db
MOCK_PID := data/.mock-api.pid
MOCK_LOG := data/b5_mock.log

.PHONY: help setup venv install start dev api web mock-api mock-stop test coverage lint typecheck \
	contract contract-check smoke e2e build exe security verify docker docker-check sample export clean

help:
	@echo "== 环境 =="
	@echo "make setup        创建 .venv + 安装前后端依赖（一条命令准备环境）"
	@echo "make install      只安装依赖（backend pyproject + frontend npm ci）"
	@echo "== 开发 =="
	@echo "make start        一键启动（单端口 8000，自动构建前端并开浏览器；给不改代码的人）"
	@echo "make dev          提示如何同时启动后端 8000 与前端 5173"
	@echo "make api          启动后端（backend.app.main:app，127.0.0.1:8000）"
	@echo "make web          启动前端 vite 5173"
	@echo "== 测试 =="
	@echo "make test         后端 pytest（单元+集成+契约）+ 前端 vitest"
	@echo "make coverage     后端覆盖率（--cov=app，门槛 70%）+ 前端覆盖率"
	@echo "make smoke        自动起 mock 服务(8004) → 跑 tests/ 30 条 smoke → 停服务"
	@echo "make e2e          Playwright 6 条（需 5173 + 8000 已启动）"
	@echo "== 质量门禁 =="
	@echo "make lint         后端 ruff + format + mypy；前端 eslint + prettier + tsc"
	@echo "make contract     导出 OpenAPI/事件快照并校验 contracts/ diff 为空"
	@echo "make lock         重新生成 deploy/requirements.lock.txt 并校验清单一致"
	@echo "make lock-check   校验 pyproject / requirements.api / lock 三份清单一致"
	@echo "make build        前端生产构建；Docker 可用时构建镜像"
	@echo "make exe          打包成 dist/Office Agent.exe（单文件，双击即用，不需要 Python/Node）"
	@echo "make security     secret/PII 扫描（CI 另含 pip-audit/npm audit/bandit）"
	@echo "make verify       本地等价六门禁：lint + test + contract + smoke + build + security"
	@echo "== 运维 =="
	@echo "make docker       docker compose up --build -d（web:8080，api:8000）"
	@echo "make docker-check docker compose config"
	@echo "make sample       生成演示用会议记录 docx"
	@echo "make export       导出四张表为 JSON"
	@echo "make clean        清理缓存、测试残留与 mock 服务"

# ---------------------------------------------------------------- 环境
setup: venv install
	@echo "环境准备完成。下一步：cp .env.example .env，然后开两个终端 make api / make web"

venv:
	@test -x "$(PY)" || python -m venv .venv
	@echo "使用 Python：$(PY)"

install:
	@if [ -f $(BACKEND_PYPROJECT) ]; then \
		echo ">> 后端：pip install -e backend（pyproject 模式）"; \
		cd backend && ../$(PY) -m pip install -i $(PIP_INDEX) -e . && cd ..; \
	else \
		echo ">> 后端：pyproject 未就绪，使用 deploy/requirements.api.txt"; \
		$(PY) -m pip install -i $(PIP_INDEX) -r deploy/requirements.api.txt; \
	fi
	$(PY) -m pip install -i $(PIP_INDEX) pytest pytest-cov httpx python-docx pypdf openpyxl jsonschema
	@if [ -f $(FRONTEND_PKG) ]; then \
		if [ -f frontend/package-lock.json ]; then cd frontend && $(NPM) ci; else cd frontend && $(NPM) install; fi; \
	else echo ">> 前端 package.json 未就绪"; fi

# ---------------------------------------------------------------- 开发
# 一键启动：给「不装 Node、不开两个终端」的人。参数透传给 scripts/launch.py
start:
	$(PY) scripts/launch.py $(ARGS)

api:
	$(PY) -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

web:
	@if [ -f frontend/package-lock.json ]; then $(NPM) --prefix frontend ci; else $(NPM) --prefix frontend install; fi
	$(NPM) --prefix frontend run dev

dev:
	@echo "请开两个终端："
	@echo "  终端 A: make api    # http://127.0.0.1:8000"
	@echo "  终端 B: make web    # http://127.0.0.1:5173"
	@echo "首次还需：cp .env.example .env（默认 mock 模式，无需真实 Key）"

mock-api:
	@mkdir -p data/b5/uploads data/b5/artifacts
	@echo ">> 启动 mock 服务 $(BASE_URL)（日志 $(MOCK_LOG)）"
	@NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
		MOCK_MODE=true ENGINE=mock DATABASE_URL=sqlite:///$(abspath $(MOCK_DB)) \
		UPLOAD_DIR=$(abspath data/b5/uploads) ARTIFACT_DIR=$(abspath data/b5/artifacts) \
		$(PY) -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8004 > $(MOCK_LOG) 2>&1 & echo $$! > $(MOCK_PID)
	@for i in $$(seq 1 60); do \
		if curl -fsS $(BASE_URL)/api/v1/health >/dev/null 2>&1; then echo "mock 服务就绪"; exit 0; fi; \
		sleep 1; \
	done; echo "mock 服务启动失败，见 $(MOCK_LOG)"; tail -50 $(MOCK_LOG); exit 1

mock-stop:
	@if [ -f $(MOCK_PID) ]; then kill $$(cat $(MOCK_PID)) 2>/dev/null || true; rm -f $(MOCK_PID); echo "mock 服务已停止"; \
	else echo "无运行中的 mock 服务"; fi

# ---------------------------------------------------------------- 测试
test:
	@if [ -f $(BACKEND_PYPROJECT) ]; then cd backend && ../$(PY) -m pytest -q; else echo "backend pyproject 缺失"; exit 1; fi
	@if [ -f $(FRONTEND_PKG) ] && node -e "const p=require('./frontend/package.json'); process.exit(p.scripts&&p.scripts.test?0:1)"; then \
		$(NPM) --prefix frontend run test; else echo "前端 vitest 未就绪"; exit 1; fi

coverage:
	cd backend && ../$(PY) -m pytest --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=70
	$(NPM) --prefix frontend run test:coverage

lint:
	cd backend && ruff check . && ruff format --check . && mypy app
	$(NPM) --prefix frontend run lint
	$(NPM) --prefix frontend run format:check
	$(NPM) --prefix frontend run typecheck

typecheck:
	cd backend && mypy app
	$(NPM) --prefix frontend run typecheck

contract:
	$(PY) scripts/export_openapi.py --check
	@if ! git ls-files --error-unmatch contracts/openapi.v1.json >/dev/null 2>&1; then \
		echo "警告：contracts/ 尚未 git add（CI 要求快照入库，否则 contract 门禁无法生效）"; \
	else git diff --exit-code contracts/ || { echo "契约快照与代码不一致：请提交 contracts/ 变更"; exit 1; }; fi
	@echo "契约快照一致"

contract-check:
	$(PY) scripts/export_openapi.py --check

# 重新生成锁定依赖（pyproject.toml 是唯一真源）
lock:
	cd backend && $(PY) -m piptools compile --quiet --strip-extras \
		--output-file=../deploy/requirements.lock.txt --resolver=backtracking pyproject.toml
	$(PY) scripts/check_requirements_sync.py

# 校验三份依赖清单一致（CI 同款）
lock-check:
	$(PY) scripts/check_requirements_sync.py

smoke: mock-api
	@set -e; \
	$(PY) -m pytest tests -q --base-url=$(BASE_URL); status=$$?; \
	$(MAKE) mock-stop; \
	exit $$status

e2e:
	@if [ ! -f $(FRONTEND_PKG) ]; then echo "前端未就绪"; exit 1; fi
	$(NPM) --prefix frontend exec playwright test

# ---------------------------------------------------------------- 构建/安全
build:
	cd frontend && $(NPM) ci && $(NPM) run build
	@if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \
		echo ">> docker compose build"; docker compose build; \
	else echo ">> Docker 不可用：跳过镜像构建（KNOWN_ISSUES #1），本项未验证"; fi

# ---------------------------------------------------------------- 打包
# 单文件 exe：给「不想装 Python / Node，只想双击就用」的人。
# 前端 dist 是打包输入（没构建过就先构建），用户数据不进 exe（见 backend/app/core/paths.py）。
exe:
	@if [ ! -f frontend/dist/index.html ]; then echo ">> 前端未构建，先构建"; cd frontend && $(NPM) run build; fi
	@$(PY) -c "import PyInstaller" >/dev/null 2>&1 || $(PY) -m pip install --disable-pip-version-check -i $(PIP_INDEX) pyinstaller
	$(PY) -m PyInstaller packaging/office_agent.spec --noconfirm --distpath dist --workpath build/pyi
	@echo ">> 产物：dist/Office Agent.exe（数据目录：%LOCALAPPDATA%\\Office Agent，可用 --data-dir 改）"

security:
	@echo ">> secret 扫描（排除 .env）"
	@if git grep -nE 'sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|-----BEGIN [A-Z ]*PRIVATE KEY-----' -- . ':(exclude).env*'; then \
		echo "发现疑似密钥"; exit 1; else echo "OK：无密钥特征"; fi
	@echo ">> PII 扫描"
	@if git grep -nE '[A-Za-z0-9._%+-]+@(qq|163|126|gmail|outlook|hotmail|foxmail)\.(com|cn)' -- . ':(exclude).env*'; then \
		echo "发现真实邮箱域名"; exit 1; else echo "OK：无真实邮箱"; fi
	@command -v pip-audit >/dev/null 2>&1 && pip-audit -r deploy/requirements.lock.txt || echo "提示：pip-audit 未安装，CI security job 会执行"
	@command -v bandit >/dev/null 2>&1 && bandit -r backend/app -x backend/tests -ll || echo "提示：bandit 未安装，CI security job 会执行"

verify: lint test contract smoke build security
	@echo "verify 完成：见上各项输出（Docker 不可用时 build 会显式跳过镜像）"

# ---------------------------------------------------------------- 运维
docker:
	docker compose up --build -d
	@echo "访问 http://127.0.0.1:8080 ；健康检查 http://127.0.0.1:8000/api/v1/health"

docker-check:
	docker compose config

sample:
	$(PY) scripts/make_sample.py --out data/samples/meeting_notes.docx

export:
	$(PY) scripts/export.py --out data/export/export.json

clean:
	-@$(MAKE) mock-stop >/dev/null 2>&1 || true
	rm -rf .pytest_cache backend/.pytest_cache tests/.pytest_cache scripts/.pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf oam_* pytest-of-* pip-* 2>/dev/null || true
	rm -rf backend/coverage.xml backend/.coverage frontend/coverage 2>/dev/null || true
	rm -f $(MOCK_PID)
