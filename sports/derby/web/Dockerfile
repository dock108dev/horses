FROM node:20-bookworm-slim

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install

# Copy the rest of the source.
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
