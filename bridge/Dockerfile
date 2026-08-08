FROM node:22-slim
WORKDIR /bridge
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-fund --no-audit
COPY src ./src
# Sesiones de WhatsApp persistidas en volumen
VOLUME ["/bridge/sessions"]
EXPOSE 3001
CMD ["node", "src/server.js"]
