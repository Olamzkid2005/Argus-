FROM node:18-alpine AS base
WORKDIR /app

# Install ALL dependencies (including devDependencies) for build
COPY package.json package-lock.json ./
RUN npm ci

# Copy source
COPY . .

# Build
RUN npm run build

# Production stage
FROM node:18-alpine AS production
WORKDIR /app
ENV NODE_ENV=production

# Copy standalone build output and static assets
COPY --from=base /app/.next/standalone ./
COPY --from=base /app/.next/static ./.next/static
COPY --from=base /app/public ./public

# Install production deps only (separate from build stage)
COPY package.json package-lock.json ./
RUN npm ci --only=production

EXPOSE 3000
CMD ["node", "server.js"]
