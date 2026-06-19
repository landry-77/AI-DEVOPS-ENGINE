.PHONY: help setup sandbox up up-prod down logs status demo clean

help:
	@echo "AI DevOps Engine — Makefile Quickstart"
	@echo ""
	@echo "  make setup     One-command quickstart (secrets + .env + certs)"
	@echo "  make sandbox   Pre-bake sandbox Docker images"
	@echo "  make up        Launch local dev stack (docker-compose.local.yml)"
	@echo "  make up-prod   Launch production stack (docker-compose.yml)"
	@echo "  make down      Stop all containers"
	@echo "  make logs      Tail logs from all services"
	@echo "  make status    Show container status (health checks)"
	@echo "  make demo      Send a test PR webhook via curl"
	@echo "  make clean     Stop + remove volumes + prune sandboxes"

setup:
	@echo "==> AI DevOps Engine Setup"
	@echo ""
	@if [ ! -f ".env" ]; then \
		cp .env.example .env; \
		echo "  [1/5] .env created from .env.example"; \
	else \
		echo "  [1/5] .env already exists — skipping"; \
	fi
	@echo "  [2/5] Generating DJANGO_SECRET_KEY..."
	@python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null || python -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null
	@echo "  [3/5] Generating FERNET_KEY..."
	@python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "  [WARN] cryptography not installed — install with: pip install cryptography"
	@echo ""
	@echo "  [4/5] Required: OpenRouter API key"
	@echo "    Get one free at: https://openrouter.ai/keys"
	@read -p "    Paste your sk-or-v1-... key: " key; \
		if command -v sed -i >/dev/null 2>&1; then \
			sed -i "s|OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=$$key|" .env; \
		else \
			sed -i '' "s|OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=$$key|" .env; \
		fi
	@echo "  [5/5] Creating certs/ directory..."
	@mkdir -p certs
	@echo ""
	@echo "==> Setup complete!"
	@echo "    Next steps:"
	@echo "      1. Place your GitHub App .pem in certs/github_app.pem"
	@echo "      2. Edit .env: set GITHUB_APP_IDENTIFIER and GITHUB_WEBHOOK_SECRET"
	@echo "      3. Run: make sandbox"
	@echo "      4. Run: make up"

sandbox:
	@echo "==> Pre-baking sandbox Docker images..."
	docker build -t local-pytest-sandbox -f sandbox-env/Dockerfile.python sandbox-env/
	docker build -t local-jest-sandbox -f sandbox-env/Dockerfile.javascript sandbox-env/
	@echo "==> Sandbox images ready"

up:
	@echo "==> Launching local dev stack..."
	docker compose -f docker-compose.local.yml up --build -d
	@echo ""
	@echo "    Dashboard: http://localhost:8000"
	@echo "    Gateway:   http://localhost:3000"
	@echo ""
	@echo "    To expose via ngrok: make tunnel"

up-prod:
	@echo "==> Launching production stack..."
	docker compose -f docker-compose.yml up --build -d
	@echo ""
	@echo "    Dashboard: http://localhost"
	@echo "    Gateway:   http://localhost:3000"

down:
	docker compose -f docker-compose.yml down 2>/dev/null; true
	docker compose -f docker-compose.local.yml down 2>/dev/null; true
	@echo "==> Stack stopped"

logs:
	docker compose -f docker-compose.yml logs -f 2>/dev/null || docker compose -f docker-compose.local.yml logs -f

status:
	@echo "==> Container Health"
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(edge|core|async|scheduled|enterprise|control|production|local)"

tunnel:
	@echo "==> Start ngrok in a new terminal..."
	@echo "    ngrok http http://localhost:3000"
	@echo ""
	@echo "    Then set GitHub App Webhook URL to:"
	@echo "    https://<your-id>.ngrok-free.app/webhooks/github"

demo:
	@echo "==> Sending test PR webhook to local gateway..."
	@read -p "Webhook secret (from .env): " secret; \
	payload='{"action":"opened","pull_request":{"number":1},"repository":{"id":101,"full_name":"local-org/test-repo","clone_url":"local_vfs"},"installation":{"id":202}}'; \
	sig=$$(printf '%s' "$$payload" | openssl dgst -sha256 -hmac "$$secret" | awk '{print $$NF}'); \
	curl -s -X POST http://localhost:3000/webhooks/github \
		-H "Content-Type: application/json" \
		-H "x-github-event: pull_request" \
		-H "x-hub-signature-256: sha256=$$sig" \
		-d "$$payload" | python3 -m json.tool 2>/dev/null || cat

clean:
	@echo "==> Stopping and removing all containers..."
	docker compose -f docker-compose.yml down -v 2>/dev/null; true
	docker compose -f docker-compose.local.yml down -v 2>/dev/null; true
	@echo "==> Pruning orphaned sandbox containers..."
	docker ps -a --filter "name=sandbox" --format "{{.ID}}" | xargs -r docker rm -f 2>/dev/null; true
	@echo "==> Clean complete"
