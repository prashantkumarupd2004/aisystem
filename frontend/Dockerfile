FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
# npm ci for a reproducible install (package-lock.json is committed).
RUN npm ci
COPY . .
# Build-time API URL: for a deployed frontend this must be the public
# backend URL, e.g. https://api.example.com. Defaults to localhost.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
