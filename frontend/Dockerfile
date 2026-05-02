FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps --no-audit --no-fund

# Stage build
FROM deps AS build
COPY . .
RUN npm run build

# Stage prod : nginx sert les statiques + proxy /v1 + /api -> backend
# HTTPS auto-signe pour activer le secure context navigateur (crypto.subtle).
FROM nginx:alpine AS prod
RUN apk add --no-cache openssl \
 && mkdir -p /etc/nginx/ssl \
 && openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/key.pem \
        -out /etc/nginx/ssl/cert.pem \
        -subj "/CN=harpocrate-test/O=Harpocrate Dev/C=FR" \
        -addext "subjectAltName=DNS:localhost,DNS:harpocrate-test,IP:127.0.0.1,IP:192.168.10.123"
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443
