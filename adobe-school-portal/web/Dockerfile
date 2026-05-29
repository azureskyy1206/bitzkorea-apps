FROM node:20-alpine

RUN apk add --no-cache tzdata
ENV TZ=Asia/Seoul

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000
