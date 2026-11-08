# The Puxirum web panel: the built Vue app and `puxirum panel`, which serves it with a read-only API.
# Build from the repository root: docker build -f panel/Dockerfile .

FROM node:22-alpine AS web
WORKDIR /web
COPY panel/web/package.json panel/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY panel/web/ ./
RUN npm run build

FROM python:3.13-alpine
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf src
COPY --from=web /web/dist /app/web
EXPOSE 4410
# The repositories are mounted read-only at /projects; the panel finds every one with .puxirum/.
ENTRYPOINT ["puxirum", "panel", "--projects", "/projects", "--host", "0.0.0.0", "--web", "/app/web"]
