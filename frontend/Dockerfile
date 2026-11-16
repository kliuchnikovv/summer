FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

# Dev server is fine for the demo; swap for `npm run build && npm start` in production.
CMD ["npm", "run", "dev"]
