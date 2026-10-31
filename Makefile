.PHONY: dev audit audit-mobile audit-desktop audit-lighthouse audit-full audit-visual

.PHONY: demo
demo:
	npm --prefix webapp run build
	uv run --frozen python scripts/demo.py

dev:
	@bash -c '\
		set -e -m; \
		cleanup() { kill -- -$$backend_pid -$$frontend_pid 2>/dev/null || true; wait 2>/dev/null || true; }; \
		trap cleanup INT TERM EXIT; \
		(uv run python -m jobweaver.server 2>&1 | sed "s/^/[backend] /") & \
		backend_pid=$$!; \
		( cd webapp && npm run dev 2>&1 | sed "s/^/[frontend] /" ) & \
		frontend_pid=$$!; \
		while kill -0 "$$backend_pid" 2>/dev/null && kill -0 "$$frontend_pid" 2>/dev/null; do sleep 1; done; \
	'

audit:
	uv run python scripts/ux_audit.py --device all

audit-mobile:
	uv run python scripts/ux_audit.py --device pixel9

audit-desktop:
	uv run python scripts/ux_audit.py --device desktop

audit-lighthouse:
	uv run python scripts/lighthouse_audit.py --preset all

audit-full: audit audit-lighthouse

audit-visual:
	uv run python scripts/visual_heuristic_audit.py

verify-typst-wasm:
	uv run python scripts/verify_typst_wasm.py
