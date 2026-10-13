# Frontend: Vite builds the React app into static files, then nginx serves them and forwards /api to the backend.
# Built and started by docker-compose.yml.
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY public ./public
COPY src ./src
# Where the user's browser reaches the draw.io editor (baked into the build)
ARG VITE_DRAWIO_URL=http://localhost:8080
ENV VITE_DRAWIO_URL=$VITE_DRAWIO_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
