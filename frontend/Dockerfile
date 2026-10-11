FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stable nginx line that keeps getting rebuilt; non-root build (uid 101). It binds 80/443 thanks to the
# net.ipv4.ip_unprivileged_port_start sysctl in docker-compose.yml (container namespace only).
FROM nginxinc/nginx-unprivileged:1.30-alpine
# Pick up Alpine security fixes newer than the base image (e.g. libtiff).
USER root
RUN apk upgrade --no-cache
USER 101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
