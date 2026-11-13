FROM node:22.13.0-bookworm-slim
WORKDIR /app
COPY phystech-trace/services/structured-extraction/runtime/package.json ./package.json
COPY phystech-trace/services/structured-extraction/runtime/package-lock.json ./package-lock.json
RUN npm ci --omit=dev --no-audit --no-fund
COPY phystech-trace/services/structured-extraction/runtime/server.mjs ./runtime/server.mjs
COPY phystech-trace/services/structured-extraction/runtime/openapi.json ./runtime/openapi.json
COPY phystech-trace/services/structured-extraction/lib ./lib
COPY phystech-trace/contracts ./contracts
ENV NODE_ENV=production PORT=8082
EXPOSE 8082
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 CMD node -e "fetch('http://127.0.0.1:8082/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "runtime/server.mjs"]
