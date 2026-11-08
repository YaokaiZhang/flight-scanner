FROM node:22-slim AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_OUTPUT_STANDALONE=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
# Next.js writes its cache here at runtime. Group 0 may write too, for OpenShift's random user ID.
RUN mkdir -p .next/cache && chgrp -R 0 .next/cache && chmod -R g=u .next/cache
EXPOSE 3000
CMD ["node", "server.js"]
