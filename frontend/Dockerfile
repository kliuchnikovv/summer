FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# Next.js inlines NEXT_PUBLIC_* at build time, so the API base must be known now.
# Locally it defaults to http://localhost:8000; on Railway pass the api's public URL as a build arg.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

EXPOSE 3000

# Production server; honors $PORT (Railway/PaaS), falls back to 3000 locally.
CMD ["sh", "-c", "npx next start -p ${PORT:-3000}"]
