# ── Stage 1: Install dependencies ─────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

# ── Stage 2: Build ────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# BACKEND_URL is read at runtime by next.config.ts rewrites(),
# but set here so the build succeeds if anything reads it at build time.
ENV BACKEND_URL="http://backend:8000"
# NEXT_PUBLIC_BACKEND_URL="" means client fetches use relative paths → nginx routes them
ENV NEXT_PUBLIC_BACKEND_URL=""

RUN npm run build

# ── Stage 3: Production runtime ───────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# standalone output is self-contained (no node_modules needed)
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
# Rewrites in next.config.ts proxy /api/* to this URL at runtime
ENV BACKEND_URL="http://backend:8000"

CMD ["node", "server.js"]
