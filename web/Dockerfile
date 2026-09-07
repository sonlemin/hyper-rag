# Image web (story 4.1): Next.js 16.3.3 build standalone, chay bang node:20-alpine.
# Build context la thu muc web/ (xem docker-compose.yml). Ba tang: cai dependency
# tu package-lock (npm ci), `next build`, roi image chay chi mang .next/standalone
# + .next/static. Rewrite `/api/*` -> API_NOI_BO dong bang luc build, nen bien
# do vao bang ARG o tang build (compose truyen qua `build.args`); mac dinh
# `http://api:8000` la ten service trong network compose.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG API_NOI_BO=http://api:8000
ENV API_NOI_BO=$API_NOI_BO \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    # Docker dat HOSTNAME = id container; server.js cua Next bind theo bien nay,
    # nen phai ep ve 0.0.0.0 de cong publish tra loi. Node khi do chi nghe IPv4,
    # va `localhost` trong alpine phan giai ra ::1 truoc - healthcheck trong
    # compose vi the goi 127.0.0.1:3000 (do 07/09/2026, tests/test_compose_ha_tang.py canh).
    HOSTNAME=0.0.0.0
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
